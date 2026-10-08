import json, sys
import time
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

INPUT = "editor_queue.json"
OUTPUT = "predictor_queue.json"

def clamp(x, a=0, b=100):
    return max(a, min(b, x))

from metrics import aggregate_topic_stats, topic_age_hours


def stats(t):
    return aggregate_topic_stats(t.get("members", []))

def predict(t):
    text = (t.get("text") or "").lower()
    content_type = t.get("content_type", "")
    status = t.get("status", "")
    viral = float(t.get("viral_score", 0) or 0)
    editorial = float(t.get("editorial_score", 0) or 0)
    confidence = float(t.get("confidence", 0) or 0)
    posts = int(t.get("posts", 1) or 1)
    sources = int(t.get("social_sources", 1) or 1)

    views, reposts, likes, comments = stats(t)

    # Жёсткий фильтр.
    if t.get("advertising_detected") or status == "reject":
        return {
            "priority_score": 0,
            "prediction": "⛔ НЕ БРАТЬ",
            "confidence": 0,
            "verification_required": False,
            "disclaimer_required": False
        }

    # Помощь никогда не конкурирует с новостями.
    if t.get("help_request") or content_type == "help_request":
        return {
            "priority_score": 0,
            "prediction": "⚪ НЕ НОВОСТЬ: ПОМОЩЬ",
            "confidence": 0,
            "verification_required": False,
            "disclaimer_required": False
        }

    # Жалобы — отдельный поток.
    if content_type == "complaint" or t.get("source_type") == "complaint":
        signal = viral * 0.20
        signal += min(100, views / 50) * 0.30
        signal += min(100, comments * 5) * 0.25
        signal += min(100, reposts * 10) * 0.25

        if views >= 5000:
            signal += 15
        if comments >= 10:
            signal += 10
        if reposts >= 10:
            signal += 10
        if posts >= 3 or sources >= 3:
            signal += 10

        signal = clamp(signal)

        return {
            "priority_score": round(signal, 1),
            "prediction": (
                "🔥 ВИРУСНЫЙ СИГНАЛ: ЖАЛОБА"
                if signal >= 55
                else "🔵 НАБЛЮДАТЬ: ЖАЛОБА"
            ),
            "confidence": confidence,
            "verification_required": confidence < 50,
            "disclaimer_required": confidence < 50
        }

    # Базовый ранний прогноз.
    reach = clamp(views / 50)
    comment_signal = clamp(comments * 5)
    repost_signal = clamp(reposts * 10)

    engagement = (
        (likes + comments * 2 + reposts * 4)
        / max(views, 1)
        * 1000
    )
    engagement = clamp(engagement)

    spread = clamp(
        max(0, posts - 1) * 25 +
        max(0, sources - 1) * 20
    )

    # v5.5: сила события отдельно от текущего охвата.
    # Свежая серьёзная новость не должна теряться из-за маленького охвата.
    text_all = text

    # v5.7: более строгая проверка локальности.
    # Публикация в омской группе сама по себе не делает событие омским.
    nonlocal_words = [
        "шереметьево", "домодедово", "внуково",
        "москва", "москов", "санкт-петербург", "петербург",
        "екатеринбург", "новосибирск", "иркутск", "казань",
        "краснодар", "ростов-на-дону", "нижний новгород"
    ]
    omsk_words = [
        "омск", "омской", "омич", "омичи", "тара", "таре",
        "черлак", "маршала жукова", "лермонтова", "карла маркса",
        "герцена", "дианова", "химиков", "пархоменко"
    ]
    explicit_nonlocal = (
        any(w in text_all for w in nonlocal_words)
        and not any(w in text_all for w in omsk_words)
    )

    # v5.7: практическая польза для жителей — даже при небольшом охвате.
    practical_local = 0
    practical_pairs = [
        ("школ", "бпла"),
        ("забирать детей", "бпла"),
        ("забрать ребенка", "бпла"),
        ("департамент образования", "правил"),
        ("перекрыт", "движени"),
        ("отоплен", "горячей воды"),
        ("аварийн", "воды"),
    ]
    if any(a in text_all and b in text_all for a, b in practical_pairs):
        practical_local = 10
    event_strength = 0
    event_rules = [
        (["погиб", "погибла", "погибли", "смерт", "умер"], 18),
        (["дтп", "столкновен", "сбил", "наезд", "авар"], 14),
        (["пожар", "горит", "загорел", "возгора"], 12),
        (["взрыв", "взорвал"], 14),
        (["пропал", "пропала", "пропали", "разыскива"], 8),
        (["обруш", "разруш", "крушен"], 14),
        (["перекрыт", "перекрыли", "закрыт", "закрыли дорогу"], 8),
        (["массов", "несколько пострадав", "много пострадав"], 8),
    ]
    for words, bonus in event_rules:
        if any(w in text_all for w in words):
            event_strength = max(event_strength, bonus)

    # v5.6: свежесть и скорость распространения.
    # Свежая сильная новость получает преимущество перед старой,
    # которая просто успела накопить больше просмотров.
    members = t.get("members", [])
    primary = members[0] if members else {}
    ts = primary.get("timestamp")
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        ts = 0

    if ts > 0:
        age_hours = topic_age_hours(members, time.time())
        freshness = max(0.0, min(100.0, 100.0 - age_hours * 7.0))
        velocity_now = max(0.0, min(100.0, (views / age_hours) / 100.0))
    else:
        freshness = 0.0
        velocity_now = 0.0

    score = (
        editorial * 0.22 +
        confidence * 0.18 +
        viral * 0.12 +
        reach * 0.12 +
        comment_signal * 0.10 +
        repost_signal * 0.10 +
        engagement * 0.06 +
        spread * 0.05
        + event_strength
        + freshness * 0.05
        + velocity_now * 0.05
        + (practical_local if not explicit_nonlocal else 0)

    )

    # Ключевая поправка v5.4:
    # подтверждённая редактором новость получает приоритет,
    # даже если ещё не успела набрать большой охват.
    if status == "take_now":
        score += 18
    elif status == "check":
        score += 8

    if t.get("official_attribution"):
        score += 8

    # Несколько источников одной темы — ранний признак распространения.
    if posts >= 2:
        score += min(8, (posts - 1) * 4)
    if sources >= 2:
        score += min(8, (sources - 1) * 4)

    # Локальные крючки.
    hooks = [
        "погиб", "погибла", "пожар", "дтп", "авар", "пропал",
        "задерж", "снес", "запрет", "закро", "отключ",
        "дети", "мост", "газ", "отоплен", "вода",
        "омск", "омской", "омич", "омичи"
    ]
    score += min(10, sum(1 for x in hooks if x in text) * 2)

    # Чужие темы не должны попадать в лидеры.
    if explicit_nonlocal:
        score = min(score, 20)
    elif t.get("nonlocal_detected"):
        score = min(score, 35)

    score = round(clamp(score), 1)

    if score >= 65:
        prediction = "🟢 БРАТЬ"
    elif score >= 50:
        prediction = "🟡 БРАТЬ ПОСЛЕ БЫСТРОЙ ПРОВЕРКИ"
    elif score >= 35:
        prediction = "🔵 НАБЛЮДАТЬ"
    else:
        prediction = "⚪ НИЗКИЙ ПРИОРИТЕТ"

    return {
        "priority_score": score,
        "prediction": prediction,
        "confidence": confidence,
        "verification_required": confidence < 50,
        "disclaimer_required": confidence < 50
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
            "nonlocal_cap": 35,
            "explicit_nonlocal_cap": 20,
            "event_strength_matters": True,
            "fresh_serious_events_get_bonus": True,
            "freshness_matters": True,
            "velocity_now_matters": True,
            "fresh_news_gets_priority": True,
            "strict_nonlocal_detection": True,
            "practical_local_relevance_bonus": True
        },
        "topics": []
    }

    for topic in topics:
        item = dict(topic)
        item["prediction"] = predict(topic)
        result["topics"].append(item)

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