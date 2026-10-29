import json, re, sys
import math
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

from editorial_rules import is_excluded_topic, is_promotional, clean_legacy_metadata

def has_excluded_topic(t):
    return is_excluded_topic(t)


def has_promo_pattern(t):
    return is_promotional(t)


from metrics import aggregate_topic_stats, topic_age_hours, newest_timestamp

OMSK_TZ = timezone(timedelta(hours=6), name="Asia/Omsk")


def stats(t):
    return aggregate_topic_stats(t.get("members", []))


def _metric_coverage(members):
    """Count which audience metrics are actually present in source posts."""
    keys = ("views", "likes", "comments", "reposts")
    found = set()
    for member in members:
        post = member.get("post") if isinstance(member, dict) and isinstance(member.get("post"), dict) else member
        if not isinstance(post, dict):
            continue
        for key in keys:
            if post.get(key) is not None:
                found.add(key)
    return found


def _event_profile(text):
    """Map a story to a broad editorial event class, avoiding incidental word matches."""
    fatal_patterns = (
        r"\bпогиб(?:ла|ли|ло)?\s+(?:\d+\s+)?(?:человек|людей|мужчин\w*|женщин\w*|реб[её]нок|дети|водител\w*|пассажир\w*|рабоч\w*|сотрудник\w*|полицейск\w*)",
        r"\b(?:человек|мужчин\w*|женщин\w*|реб[её]нок|дети|водител\w*|пассажир\w*)\b.{0,40}\bпогиб\w*",
        r"\bсмертельн\w*\s+(?:дтп|авари\w*|происшеств\w*|столкновен\w*|наезд\w*)",
        r"\bумер(?:ла|ли)?\s+(?:человек|мужчин\w*|женщин\w*|реб[её]нок|пациент\w*)",
        r"\bскончал(?:ся|ась|ись)\b",
    )
    if any(re.search(pattern, text, re.I) for pattern in fatal_patterns):
        return "fatal_incident", 100.0

    profiles = (
        ("public_safety", ("эвакуир", "эвакуац", "угроз", "минирован", "подозрительн предмет", "закрыли здание"), 85),
        ("major_incident", ("взрыв", "обруш", "крушен", "крупн авар", "массов", "разрушен"), 90),
        ("fire_or_emergency", ("пожар", "горит", "загорел", "возгора", "спасател"), 75),
        ("transport_incident", ("дтп", "столкновен", "сбил", "наезд", "перекрыт", "закрыли дорогу"), 65),
        ("missing_person", ("пропал", "пропала", "пропали", "разыскива"), 55),
        ("public_decision", ("повысили тариф", "изменят тариф", "запрет", "вступит в силу", "приняли закон", "отменили маршрут", "закроют маршрут"), 45),
    )
    for event_class, patterns, impact in profiles:
        if any(pattern in text for pattern in patterns):
            return event_class, float(impact)
    return "general", 20.0


def predict(t):
    """Calculate a single editorial triage score from independent, observable features.

    Legacy analyzer scores are preserved as diagnostics but are deliberately not
    re-used here because they overlap (viral_score is already inside editorial_score
    and score). Verification confidence is returned separately from ranking.
    """
    members = t.get("members", []) or []
    newest_ts = newest_timestamp(members)
    today = datetime.now(OMSK_TZ).date()
    confidence = float(t.get("confidence", 0) or 0)

    def rejected(reason, label):
        return {
            "priority_score": 0.0,
            "prediction": label,
            "confidence": confidence,
            "eligible": False,
            "exclusion_reason": reason,
            "score_version": "editorial_v2",
        }

    if newest_ts is None:
        return rejected("not_today_or_missing_timestamp", "⛔ ИСКЛЮЧЕНО: НЕТ ДАТЫ")
    if datetime.fromtimestamp(newest_ts, OMSK_TZ).date() != today:
        return rejected("not_today_or_missing_timestamp", "⛔ ИСКЛЮЧЕНО: НЕ СЕГОДНЯ")

    text = topic_text(t)
    content_type = t.get("content_type", "")
    status = t.get("status", "")
    if has_excluded_topic(t) or t.get("excluded_topic"):
        return rejected("excluded_topic", "⛔ ИСКЛЮЧЕНО: ЗАПРЕЩЁННАЯ ТЕМА")
    if has_promo_pattern(t):
        return rejected("promotional", "⛔ ИСКЛЮЧЕНО: ПРОМО")
    # "reject" is also used by the first-stage ranker for ordinary stories
    # below its own threshold. It is not, by itself, a hard editorial exclusion.
    # Keep explicit hard exclusions here so lower-ranked local news can be scored.
    if t.get("advertising_detected") or content_type == "advertising":
        return rejected("advertising", "⛔ ИСКЛЮЧЕНО: РЕКЛАМА")
    if t.get("nonlocal_detected"):
        return rejected("nonlocal_topic", "⛔ ИСКЛЮЧЕНО: НЕ ОМСК")
    if t.get("help_request") or content_type == "help_request":
        return rejected("help_request", "⛔ ИСКЛЮЧЕНО: ПРОСЬБА О ПОМОЩИ")
    if content_type == "opinion" or t.get("opinion_detected"):
        return rejected("opinion", "⛔ ИСКЛЮЧЕНО: МНЕНИЕ")

    age_minutes = max(0.0, (time.time() - newest_ts) / 60.0)
    freshness = clamp(100.0 * (1.0 - age_minutes / 180.0))
    views, reposts, likes, comments = stats(t)
    available = _metric_coverage(members)
    has_views = "views" in available and views > 0

    # When metrics are absent, don't treat missing data as measured zero interest.
    reach = clamp(100.0 * math.log1p(max(0.0, views)) / math.log1p(50000.0)) if has_views else None
    engagement = clamp(((likes + comments * 2 + reposts * 4) / max(views, 1)) * 1000) if has_views and available.intersection({"likes", "comments", "reposts"}) else None
    discussion = clamp((comments / max(views, 1)) * 5000) if has_views and "comments" in available else None
    reshare = clamp((reposts / max(views, 1)) * 5000) if has_views and "reposts" in available else None
    velocity = clamp(100.0 * math.log1p(max(0.0, views) / max(age_minutes / 60.0, 1.0 / 60.0)) / math.log1p(50000.0)) if has_views else None

    # Local usefulness is based on the analyzer's explicit classification where available.
    if t.get("nonlocal_detected"):
        local_relevance = 0.0
    elif t.get("explicit_omsk_relevance"):
        local_relevance = 100.0
    elif any(word in text for word in ("омск", "омской", "омич", "омичи", "тара", "черлак", "калачинск", "исилькуль")):
        local_relevance = 80.0
    else:
        local_relevance = 30.0

    event_class, event_impact = _event_profile(text)
    # Score only dimensions with usable evidence; weights are renormalized so missing
    # engagement counters do not silently punish early stories.
    components = {
        "freshness": (freshness, 0.20),
        "local_relevance": (local_relevance, 0.16),
        "event_impact": (event_impact, 0.16),
        "reach": (reach, 0.12),
        "engagement": (engagement, 0.16),
        "discussion": (discussion, 0.08),
        "reshare": (reshare, 0.06),
        "velocity": (velocity, 0.06),
    }
    usable = {name: (value, weight) for name, (value, weight) in components.items() if value is not None}
    weight_total = sum(weight for _, weight in usable.values())
    score = round(clamp(sum(value * weight for value, weight in usable.values()) / weight_total), 1) if weight_total else 0.0

    # Event announcements and sports interviews are useful, but should not
    # outrank city incidents and public-interest reporting by default.
    is_sports_interview = bool(re.search(
        r"\b(?:интервью|рассказал\w*|поделил\w*\s+впечатлен\w*|после\s+матча)\b",
        text, re.I
    )) and bool(re.search(
        r"\b(?:хокке\w*|авангард\w*|футбол\w*|спортсмен\w*|матча|игрок\w*|голкипер\w*)\b",
        text, re.I
    ))
    is_event_announcement = bool(re.search(
        r"\b(?:автограф-сесси\w*|анонс\w*\s+мероприят\w*|состоится\s+(?:концерт|встреча|мероприятие|автограф))",
        text, re.I
    ))
    if is_sports_interview:
        score = min(score, 40.0)
    elif is_event_announcement:
        score = min(score, 42.0)

    if score >= 70:
        label = "🟢 ВЫСОКИЙ ПРИОРИТЕТ"
    elif score >= 45:
        label = "🟡 СРЕДНИЙ ПРИОРИТЕТ"
    else:
        label = "⚪ НИЗКИЙ ПРИОРИТЕТ"

    effective_weights = {
        name: round(weight / weight_total, 4)
        for name, (_, weight) in usable.items()
    }

    return {
        "priority_score": score,
        "prediction": label,
        "confidence": confidence,
        "eligible": True,
        "exclusion_reason": None,
        "score_version": "editorial_v2",
        "event_class": event_class,
        "metric_coverage": sorted(available),
        "coverage_ratio": round(len(available) / 4.0, 2),
        "signals": {
            name: (round(value, 1) if value is not None else None)
            for name, (value, _) in components.items()
        },
        "score_weights": effective_weights,
        "legacy_scores": {
            "analyzer_score": t.get("score"),
            "viral_score": t.get("viral_score"),
            "editorial_score": t.get("editorial_score"),
        },
    }

def apply_editorial_action(item, prediction):
    """Assign only actionable or excluded statuses; never create a holding bucket."""
    score = float(prediction.get("priority_score", 0) or 0)
    if score >= 45:
        status, action, label, mode = (
            "take_now", "БРАТЬ В РАБОТУ", "🟢 В РАБОТУ", "editorial_work",
        )
        reason = None
    else:
        status, action, label, mode = (
            "reject", "ИСКЛЮЧИТЬ", "⚪ ИСКЛЮЧИТЬ: НИЗКИЙ ПРИОРИТЕТ",
            "below_priority_threshold",
        )
        reason = "below_priority_threshold"

    item["status"] = status
    item["action"] = action
    item["editor_status"] = label
    item["publication_mode"] = mode
    item["editorial_exclusion_reason"] = reason
    return item


def main():
    path = Path(INPUT)
    if not path.exists():
        raise SystemExit(f"Не найден {INPUT}")

    data = json.loads(path.read_text(encoding="utf-8"))
    topics = data.get("topics", [])

    if not topics:
        for key in ("take_now", "reject", "unconfirmed_signals", "check", "watch"):
            topics.extend(data.get(key, []))

    result = {
        "generated_at": data.get("generated_at"),
        "version": "predictor-editorial-v2",
        "model": {
            "purpose": "единый редакционный приоритет по независимым признакам",
            "early_dynamics_priority": True,
            "canonical_score": "prediction.priority_score",
            "score_version": "editorial_v2",
            "legacy_scores_are_diagnostic_only": True,
            "missing_metrics_are_not_zero_interest": True,
            "editorial_priority_preserved": True,
            "official_news_bonus": False,
            "reach_matters": True,
            "comments_weighted": True,
            "reposts_weighted": True,
            "cross_source_spread_matters": False,
            "complaints_are_separate_signals": False,
            "help_requests_are_not_news": True,
            "advertising_is_not_news": True,
            "excluded_topics_are_hard_filtered": True,
            "promotional_topics_are_hard_filtered": True,
            "nonlocal_cap": 35,
            "explicit_nonlocal_cap": 20,
            "event_strength_matters": True,
            "event_classification": "broad editorial taxonomy",
            "freshness_matters": True,
            "freshness_window_minutes": 180,
            "base_weights": {"freshness": 0.20, "local_relevance": 0.16, "event_impact": 0.16, "reach": 0.12, "engagement": 0.16, "discussion": 0.08, "reshare": 0.06, "velocity": 0.06},
            "confidence_is_diagnostic_only": True,
            "workflow_status_bonus": False,
            "single_ranked_queue": True,
            "today_only_timezone": "Asia/Omsk",
            "wide_source_saturation_penalty": False,
            "velocity_now_matters": True,
            "fresh_news_gets_priority": True,
            "strict_nonlocal_detection": True,
            "practical_local_relevance_bonus": True
        },
        "topics": []
    }

    excluded_count = 0
    for raw_topic in topics:
        topic = clean_legacy_metadata(raw_topic)
        if not isinstance(topic, dict):
            continue
        item = dict(topic)
        item["prediction"] = predict(topic)
        prediction = item["prediction"]
        if not prediction.get("eligible", False):
            excluded_count += 1
            continue

        apply_editorial_action(item, prediction)
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
