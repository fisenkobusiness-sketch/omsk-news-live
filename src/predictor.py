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

from editorial_rules import is_excluded_topic, is_promotional, clean_legacy_metadata, topic_text

def clamp(x, a=0, b=100):
    return max(a, min(b, x))


def has_excluded_topic(t):
    return is_excluded_topic(t)


def has_promo_pattern(t):
    return is_promotional(t)


from metrics import aggregate_topic_stats, topic_age_hours, newest_timestamp
from ml_model import features_for_topic, predict as ml_predict

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


def _source_spread(members):
    """Score spread across distinct named sources, not duplicate posts from one source."""
    source_keys = ("source", "source_name", "group_name", "community_name", "source_id", "group_id")
    sources = set()
    for member in members or []:
        post = member.get("post") if isinstance(member, dict) and isinstance(member.get("post"), dict) else member
        if not isinstance(post, dict):
            continue
        source = next((post.get(key) for key in source_keys if post.get(key) not in (None, "")), None)
        if source is not None:
            sources.add(str(source).strip().casefold())
    if not sources:
        return None, 0
    count = len(sources)
    # Two independent sources are already a meaningful early signal; returns
    # diminish as more sources repeat the same story.
    score = clamp(100.0 * (1.0 - math.exp(-(count - 1) / 2.0)))
    return score, count


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
    source_spread, source_count = _source_spread(members)
    is_complaint = (
        content_type == "complaint"
        or bool(t.get("complaint_signal"))
        or bool(t.get("complaint_detected"))
    )
    # Score only dimensions with usable evidence; weights are renormalized so missing
    # engagement counters do not silently punish early stories. Independent-source
    # spread is a separate early signal, not a proxy for official confirmation.
    components = {
        "freshness": (freshness, 0.20),
        "local_relevance": (local_relevance, 0.16),
        "event_impact": (event_impact, 0.16),
        "reach": (reach, 0.10),
        "engagement": (engagement, 0.14),
        "discussion": (discussion, 0.07),
        "reshare": (reshare, 0.05),
        "velocity": (velocity, 0.06),
        "cross_source_spread": (source_spread, 0.06),
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

    # A rapidly spreading public complaint can be a local-news signal even when
    # it is not a conventional news report. Do not require official confirmation.
    complaint_is_viral = is_complaint and (
        views >= 5000 or reposts >= 10 or len(members) >= 3 or source_count >= 3
    )
    complaint_bonus = 8.0 if complaint_is_viral else 0.0
    score = round(clamp(score + complaint_bonus), 1)

    # Train on the tracker’s 3-hour engagement checkpoints. Until enough labeled
    # examples exist, retain the established editorial score as a safe fallback.
    model_input = dict(t)
    model_input["prediction"] = {"priority_score": score}
    model_features = features_for_topic(model_input)
    predicted_engagement_3h, model_samples_3h, model_scale_3h = ml_predict(model_features, horizon=3)
    predicted_engagement_1h, model_samples_1h, _ = ml_predict(model_features, horizon=1)
    audience_predictions = {}
    for audience_name in ("golos", "zhest"):
        target_1h, target_n1h, _ = ml_predict(model_features, horizon=1, audience=audience_name)
        target_3h, target_n3h, target_scale = ml_predict(model_features, horizon=3, audience=audience_name)
        audience_predictions[audience_name] = {
            "engagement_1h": round(target_1h, 6) if target_1h is not None else None,
            "engagement_3h": round(target_3h, 6) if target_3h is not None else None,
            "priority_score": round(clamp(100.0 * target_3h / max(target_scale, 1e-6)), 1) if target_3h is not None else None,
            "training_samples_1h": target_n1h,
            "training_samples_3h": target_n3h,
        }
    ml_score = None
    if predicted_engagement_3h is not None:
        ml_score = round(clamp(100.0 * predicted_engagement_3h / max(model_scale_3h, 1e-6)), 1)
        # Shadow mode: collect model predictions for evaluation without changing
        # editorial decisions until the holdout results are stable by audience.

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
        "model_type": "ridge_engagement_v1_shadow" if ml_score is not None or predicted_engagement_1h is not None else "editorial_v2_fallback",
        "ml_priority_score": ml_score,
        "training_samples_1h": model_samples_1h,
        "training_samples_3h": model_samples_3h,
        "predicted_engagement_1h": round(predicted_engagement_1h, 6) if predicted_engagement_1h is not None else None,
        "predicted_engagement_3h": round(predicted_engagement_3h, 6) if predicted_engagement_3h is not None else None,
        "audience_model_predictions": audience_predictions,
        "event_class": event_class,
        "complaint_signal": is_complaint,
        "complaint_viral_signal": complaint_is_viral,
        "complaint_bonus": complaint_bonus,
        "cross_source_count": source_count,
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


MIN_CONSOLE_MODEL_SAMPLES = 30
MAX_CONSOLE_CANDIDATES = 10
CONSOLE_FRESHNESS_SECONDS = 180 * 60
CONSOLE_SPREAD_WINDOW_SECONDS = 30 * 60
CONSOLE_SPREAD_MIN_SOURCES = 3


def audience_ml_rank(topic):
    """Return the strongest usable 3-hour audience-model prediction."""
    models = (topic.get("prediction") or {}).get("audience_model_predictions") or {}
    candidates = {}
    for key, label in (("golos", "Г"), ("zhest", "Ж")):
        model = models.get(key)
        if not isinstance(model, dict):
            continue
        score = model.get("priority_score")
        samples = model.get("training_samples_3h")
        if (
            isinstance(score, (int, float))
            and isinstance(samples, int)
            and samples >= MIN_CONSOLE_MODEL_SAMPLES
        ):
            candidates[key] = {"score": float(score), "label": label, "samples": samples}
    if not candidates:
        return None
    best_key = max(candidates, key=lambda key: candidates[key]["score"])
    best = candidates[best_key]
    if (
        len(candidates) == 2
        and abs(candidates["golos"]["score"] - candidates["zhest"]["score"]) < 0.05
    ):
        return {
            "score": best["score"],
            "label": "Г/Ж",
            "samples": f'{candidates["golos"]["samples"]}/{candidates["zhest"]["samples"]}',
        }
    return best


def recent_source_count(topic, now=None):
    """Count distinct monitored source accounts reporting the topic in the last 30 minutes."""
    now = time.time() if now is None else now
    sources = set()
    for member in topic.get("members", []) or []:
        if not isinstance(member, dict):
            continue
        try:
            timestamp = float(member.get("timestamp") or 0)
        except (TypeError, ValueError):
            continue
        if not 0 <= now - timestamp <= CONSOLE_SPREAD_WINDOW_SECONDS:
            continue
        source = str(
            member.get("source_name") or member.get("source") or member.get("url") or ""
        ).strip().casefold()
        if source:
            sources.add(source)
    return len(sources)


def console_ml_candidates(topics):
    """Mirror the bot's ML, freshness, link, and rapid-spread ranking."""
    candidates = []
    now = time.time()
    for topic in topics:
        prediction = topic.get("prediction") or {}
        if prediction.get("eligible") is not True:
            continue
        timestamp = newest_timestamp(topic.get("members", []))
        if timestamp is None or not 0 <= now - timestamp <= CONSOLE_FRESHNESS_SECONDS:
            continue
        has_source = bool(
            topic.get("primary_url")
            or topic.get("source_urls")
            or any(
                isinstance(member, dict) and member.get("url")
                for member in topic.get("members", [])
            )
        )
        if not has_source:
            continue
        rank = audience_ml_rank(topic)
        if rank is None:
            continue
        spread_count = recent_source_count(topic, now)
        candidates.append((topic, rank, spread_count))
    candidates.sort(
        key=lambda item: (
            item[2] >= CONSOLE_SPREAD_MIN_SOURCES,
            item[2],
            item[1]["score"],
            float((item[0].get("prediction") or {}).get("priority_score") or 0),
        ),
        reverse=True,
    )
    return candidates[:MAX_CONSOLE_CANDIDATES]


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
            "cross_source_spread_matters": True,
            "complaints_are_separate_signals": True,
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
            "base_weights": {"freshness": 0.20, "local_relevance": 0.16, "event_impact": 0.16, "reach": 0.10, "engagement": 0.14, "discussion": 0.07, "reshare": 0.05, "velocity": 0.06, "cross_source_spread": 0.06},
            "viral_complaint_bonus": 8,
            "viral_complaint_threshold": "views>=5000 OR reposts>=10 OR posts>=3 OR independent_sources>=3",
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
    console_print("\nТОП-5 рекомендаций бота: ML-прогноз + быстрый рост темы")
    ml_candidates = console_ml_candidates(result["topics"])
    if not ml_candidates:
        console_print("Нет свежих тем с обученной моделью и прямой ссылкой.")
    for i, (topic, rank, spread_count) in enumerate(ml_candidates[:5], 1):
        title = (topic.get("text") or "").replace("\n", " ")[:100]
        signal = f"быстро в {spread_count} источниках" if spread_count >= CONSOLE_SPREAD_MIN_SOURCES else "ML"
        console_print(
            f"{i}. {rank['score']:.1f} — {rank['label']} — {signal} — замеры: {rank['samples']} — {title}"
        )


if __name__ == "__main__":
    main()
