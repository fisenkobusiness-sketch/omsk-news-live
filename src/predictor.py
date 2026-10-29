import json, sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Prefer UTF-8; if the host console is legacy, console_print below falls back safely.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


def console_print(message):
    """Print without allowing a legacy Windows console to crash the process."""
    text = str(message)
    try:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        text.encode(encoding)
        print(text, flush=True)
    except (UnicodeEncodeError, LookupError):
        print(text.encode("ascii", "backslashreplace").decode("ascii"), flush=True)

INPUT = "runtime/editor_queue.json"
OUTPUT = "runtime/predictor_queue.json"

EXCLUDED_TOPIC_PATTERNS = [
    "бпла", "беспилотник", "беспилотники", "беспилотный",
    "беспилотные", "дрон", "дроны", "дрона", "дронами",
    "воздушная тревога", "воздушной тревоги", "ракетной опасности",
]

PROMO_PATTERNS = [
    "подписывайтесь", "подпишитесь", "подписывайся",
    "наши каналы", "самые свежие новости",
    "где публикуются самые свежие",
]


def clamp(x, a=0, b=100):
    return max(a, min(b, x))


def topic_text(t):
    parts = [
        t.get("text"),
        t.get("title"),
        t.get("headline"),
        t.get("summary"),
    ]
    for member in t.get("members", []) or []:
        if isinstance(member, dict):
            parts.append(member.get("text"))
            parts.append(member.get("title"))
    return " ".join(str(x or "").lower() for x in parts)


def has_excluded_topic(t):
    text = topic_text(t)
    return any(pattern in text for pattern in EXCLUDED_TOPIC_PATTERNS)


def has_promo_pattern(t):
    text = topic_text(t)
    return any(pattern in text for pattern in PROMO_PATTERNS)


from metrics import aggregate_topic_stats, topic_age_hours, newest_timestamp

OMSK_TZ = timezone(timedelta(hours=6), name="Asia/Omsk")


def stats(t):
    return aggregate_topic_stats(t.get("members", []))


def predict(t):
    """Rank eligible local stories by audience-interest signals.

    Confidence and workflow status are verification metadata, not popularity
    bonuses. The output remains one sorted queue; hard exclusions score zero.
    """
    members = t.get("members", []) or []
    newest_ts = newest_timestamp(members)
    today = datetime.now(OMSK_TZ).date()

    def rejected(reason, label):
        return {
            "priority_score": 0,
            "prediction": label,
            "confidence": float(t.get("confidence", 0) or 0),
            "verification_required": float(t.get("confidence", 0) or 0) < 50,
            "disclaimer_required": float(t.get("confidence", 0) or 0) < 50,
            "eligible": False,
            "exclusion_reason": reason,
        }

    if newest_ts is None:
        return rejected("not_today_or_missing_timestamp", "⛔ ИСКЛЮЧЕНО: НЕТ ДАТЫ")
    if datetime.fromtimestamp(newest_ts, OMSK_TZ).date() != today:
        return rejected("not_today_or_missing_timestamp", "⛔ ИСКЛЮЧЕНО: НЕ СЕГОДНЯ")

    text = topic_text(t)
    content_type = t.get("content_type", "")
    status = t.get("status", "")
    confidence = float(t.get("confidence", 0) or 0)
    viral = clamp(float(t.get("viral_score", 0) or 0))
    editorial = clamp(float(t.get("editorial_score", 0) or 0))
    posts = int(t.get("posts", len(members) or 1) or 1)
    sources = int(t.get("social_sources", 1) or 1)
    views, reposts, likes, comments = stats(t)

    # Apply eligibility filters before any ranking signals.
    if has_excluded_topic(t) or t.get("excluded_topic"):
        return rejected("excluded_topic", "⛔ ИСКЛЮЧЕНО: ЗАПРЕЩЁННАЯ ТЕМА")
    if has_promo_pattern(t):
        return rejected("promotional", "⛔ ИСКЛЮЧЕНО: ПРОМО")
    if t.get("advertising_detected") or status == "reject" or content_type == "advertising":
        return rejected("advertising_or_rejected", "⛔ ИСКЛЮЧЕНО: РЕКЛАМА/ОТКЛОНЕНО")
    if t.get("help_request") or content_type == "help_request":
        return rejected("help_request", "⛔ ИСКЛЮЧЕНО: ПРОСЬБА О ПОМОЩИ")
    if content_type == "opinion" or t.get("opinion_detected"):
        return rejected("opinion", "⛔ ИСКЛЮЧЕНО: МНЕНИЕ")

    age_minutes = max(0.0, (time.time() - newest_ts) / 60.0)
    age_hours = max(1.0 / 60.0, age_minutes / 60.0)

    # Smooth logarithmic reach prevents large raw view counts from swallowing
    # all other signals. Interaction rates preserve early signals on small reach.
    reach = clamp(100.0 * math.log1p(max(0.0, views)) /
                  __import__("math").log1p(50000.0))
    engagement_rate = clamp(
        ((likes + comments * 2 + reposts * 4) / max(views, 1)) * 1000
    )
    comment_signal = clamp((comments / max(views, 1)) * 5000)
    repost_signal = clamp((reposts / max(views, 1)) * 5000)
    velocity = clamp(
        100.0 * __import__("math").log1p(max(0.0, views) / age_hours) /
        __import__("math").log1p(50000.0)
    )
    freshness = clamp(100.0 * (1.0 - age_minutes / 180.0))

    # A single interpretable score: audience signals + editorial relevance.
    # Confidence, official attribution and workflow status do not add popularity.
    score = (
        editorial * 0.22
        + viral * 0.20
        + reach * 0.12
        + engagement_rate * 0.14
        + comment_signal * 0.10
        + repost_signal * 0.10
        + velocity * 0.08
        + freshness * 0.04
    )

    # Event importance and local usefulness provide only a small tie-breaker.
    event_rules = [
        (("погиб", "погибла", "погибли", "смерт", "умер"), 7),
        (("дтп", "столкновен", "сбил", "наезд", "авар"), 5),
        (("пожар", "горит", "загорел", "возгора"), 4),
        (("взрыв", "взорвал", "обруш", "разруш", "крушен"), 5),
        (("пропал", "пропала", "пропали", "разыскива"), 3),
        (("перекрыт", "перекрыли", "закрыли дорогу"), 2),
    ]
    for words, bonus in event_rules:
        if any(word in text for word in words):
            score += bonus
            break

    local_words = ("омск", "омской", "омич", "омичи", "тара", "черлак", "калачинск")
    nonlocal_words = (
        "шереметьево", "домодедово", "внуково", "москва", "москов",
        "санкт-петербург", "петербург", "екатеринбург", "новосибирск",
        "иркутск", "казань", "краснодар", "ростов-на-дону", "нижний новгород"
    )
    local = any(word in text for word in local_words)
    explicit_nonlocal = any(word in text for word in nonlocal_words) and not local
    if local:
        score += 3
    if explicit_nonlocal or t.get("nonlocal_detected"):
        score = min(score, 20 if explicit_nonlocal else 35)

    score = round(clamp(score), 1)
    if score >= 65:
        label = "🟢 ВЫСОКИЙ ПОТЕНЦИАЛ"
    elif score >= 45:
        label = "🟡 СРЕДНИЙ ПОТЕНЦИАЛ"
    else:
        label = "⚪ НИЗКИЙ ПОТЕНЦИАЛ"

    return {
        "priority_score": score,
        "prediction": label,
        "confidence": confidence,
        "verification_required": confidence < 50,
        "disclaimer_required": confidence < 50,
        "eligible": True,
        "exclusion_reason": None,
        "signals": {
            "reach": round(reach, 1),
            "engagement_rate": round(engagement_rate, 1),
            "comment_rate": round(comment_signal, 1),
            "repost_rate": round(repost_signal, 1),
            "velocity": round(velocity, 1),
            "freshness": round(freshness, 1),
        },
    }


def main():
    path = Path(INPUT)
    if not path.exists():
        raise SystemExit(f"Не найден {INPUT}")

    data = json.loads(path.read_text(encoding="utf-8"))
    topics = data.get("topics", [])

    if not topics:
        for key in ("take_now", "unconfirmed_signals", "check", "watch", "reject"):
            topics.extend(data.get(key, []))

    result = {
        "generated_at": data.get("generated_at"),
        "version": "predictor",
        "model": {
            "purpose": "раннее выявление потенциально сильных материалов",
            "early_dynamics_priority": True,
            "editorial_priority_preserved": True,
            "official_news_bonus": True,
            "reach_matters": True,
            "comments_weighted": True,
            "reposts_weighted": True,
            "cross_source_spread_matters": True,
            "complaints_are_separate_signals": True,
            "help_requests_are_not_news": True,
            "advertising_is_not_news": True,
            "excluded_topics_are_hard_filtered": True,
            "promotional_topics_are_hard_filtered": True,
            "nonlocal_cap": 35,
            "explicit_nonlocal_cap": 20,
            "event_strength_matters": True,
            "fresh_serious_events_get_bonus": True,
            "freshness_matters": True,
            "freshness_window_minutes": 180,
            "freshness_weight": 0.04,\n            "confidence_is_verification_only": True,\n            "workflow_status_bonus": False,\n            "single_ranked_queue": True,
            "today_only_timezone": "Asia/Omsk",
            "wide_source_saturation_penalty": True,
            "velocity_now_matters": True,
            "fresh_news_gets_priority": True,
            "strict_nonlocal_detection": True,
            "practical_local_relevance_bonus": True
        },
        "topics": []
    }

    excluded_count = 0
    for topic in topics:
        item = dict(topic)
        item["prediction"] = predict(topic)
        if not item["prediction"].get("eligible", False):
            excluded_count += 1
            continue
        result["topics"].append(item)

    result["excluded_topics_count"] = excluded_count
    result["topics"].sort(
        key=lambda x: x["prediction"]["priority_score"],
        reverse=True
    )

    Path(OUTPUT).write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    console_print(f"Готово: {OUTPUT}")
    console_print("\nТОП-5:")
    for i, topic in enumerate(result["topics"][:5], 1):
        p = topic["prediction"]
        title = (topic.get("text") or "").replace("\n", " ")[:100]
        console_print(f"{i}. {p['priority_score']} - {p['prediction']} - {title}")


if __name__ == "__main__":
    main()
