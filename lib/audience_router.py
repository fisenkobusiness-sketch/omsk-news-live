# -*- coding: utf-8 -*-
"""Калибровка и безопасный роутинг свежих новостей между аудиториями.

Важно:
- raw score разных пабликов напрямую НЕ сравнивается;
- fit считается относительно исторического распределения score той же модели
  внутри той же аудитории;
- механизмные профили сохраняются как диагностический слой;
- production routing остаётся выключенным до OOS-проверки.
"""
from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from statistics import mean, median
from datetime import datetime, timezone


DEFAULT_AUDIENCES = ("golos", "zhest")
LOW_MARGIN = 5.0
HIGH_MARGIN = 12.0
MIN_PROFILE_POSTS = 50
MIN_MECHANISM_POSTS = 20


def _num(value, default=0.0):
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _percentile_from_sorted(sorted_values, value):
    """Fast percentile using binary search."""
    if not sorted_values:
        return 50.0

    n = len(sorted_values)
    value = _num(value)

    if n == 1:
        return 100.0 if value >= sorted_values[0] else 0.0

    left = bisect_left(sorted_values, value)
    right = bisect_right(sorted_values, value)
    equal = right - left
    rank = left + 0.5 * equal

    return round(
        max(0.0, min(100.0, rank / n * 100.0)),
        2,
    )


def percentile_of_value(value, values):
    """Compatibility wrapper; sorts only when needed by callers."""
    return _percentile_from_sorted(
        sorted(_num(v) for v in values),
        value,
    )
def _quantile(values, q):
    xs = sorted(_num(v) for v in values)
    if not xs:
        return 50.0
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _score_history(posts, audience, model):
    """Score one audience history once, reusing one classification per post."""
    try:
        from lib.analytics_core import (
            prepare_fresh_classification,
            score_fresh_post,
        )
    except ImportError:
        from analytics_core import (
            prepare_fresh_classification,
            score_fresh_post,
        )

    rows = [
        post for post in posts
        if post.get("audience") == audience
    ]

    scores = []
    pairs = []

    for post in rows:
        classification = prepare_fresh_classification(post)
        scored = score_fresh_post(
            post,
            model,
            classification=classification,
        )
        score = _num(
            scored.get("potential_score"),
            50.0,
        )
        observed = _num(
            post.get("potential"),
            0.0,
        )
        scores.append(score)
        pairs.append((score, observed))

    return rows, scores, pairs
def build_score_calibration(posts, audience, model, history=None):
    """Build model-score -> observed-potential calibration once."""
    if history is None:
        history = _score_history(
            posts,
            audience,
            model,
        )

    _, scores, pairs = history

    if not scores:
        return {
            "method": "model_score_to_observed_potential_bins",
            "posts": 0,
            "bins": [],
        }

    pairs = sorted(
        pairs,
        key=lambda item: item[0],
    )
    n = len(pairs)
    bin_size = max(40, n // 20)

    bins = []
    for start in range(0, n, bin_size):
        chunk = pairs[start:start + bin_size]
        if not chunk:
            continue

        score_values = [
            item[0] for item in chunk
        ]
        observed = [
            item[1] for item in chunk
        ]

        bins.append({
            "score_min": round(
                min(score_values),
                3,
            ),
            "score_max": round(
                max(score_values),
                3,
            ),
            "score_mid": round(
                mean(score_values),
                3,
            ),
            "expected_potential": round(
                mean(observed),
                3,
            ),
            "observed_potential_median": round(
                median(observed),
                3,
            ),
            "posts": len(chunk),
        })

    return {
        "method": "model_score_to_observed_potential_bins",
        "posts": n,
        "bins": bins,
        "target": "observed_potential",
        "target_scale": "0..100",
    }
def _interpolate(x1, y1, x2, y2, x):
    if x2 == x1:
        return (y1 + y2) / 2.0
    ratio = (x - x1) / (x2 - x1)
    return y1 + (y2 - y1) * ratio


def calibrated_expected_potential(score, profile):
    """Map an audience-specific model score onto common observed-potential scale."""
    calibration = profile.get("score_calibration") or {}
    bins = calibration.get("bins") or []
    if not bins:
        # Safe fallback only when calibration is unavailable.
        return _num(score, 50.0), 0.0, "fallback"

    x = _num(score, 50.0)
    points = [
        (_num(b.get("score_mid")), _num(b.get("expected_potential")), int(b.get("posts", 0) or 0))
        for b in bins
    ]
    points = [p for p in points if p[2] > 0]
    if not points:
        return x, 0.0, "fallback"

    if len(points) == 1:
        return max(0.0, min(100.0, points[0][1])), points[0][2], "single_bin"

    if x <= points[0][0]:
        p1, p2 = points[0], points[1]
    elif x >= points[-1][0]:
        p1, p2 = points[-2], points[-1]
    else:
        p1, p2 = points[0], points[1]
        for left, right in zip(points, points[1:]):
            if left[0] <= x <= right[0]:
                p1, p2 = left, right
                break

    y = _interpolate(p1[0], p1[1], p2[0], p2[1], x)
    y = max(0.0, min(100.0, y))
    density = p1[2] + p2[2]
    return round(y, 2), density, "linear_bin_interpolation"


def build_audience_profile(
    posts,
    audience,
    model=None,
    min_posts=MIN_PROFILE_POSTS,
    history=None,
):
    """Build one audience profile with no duplicate model scoring."""
    rows = [
        post for post in posts
        if post.get("audience") == audience
    ]

    if len(rows) < min_posts:
        raise ValueError(
            f"Недостаточно истории для {audience}: "
            f"{len(rows)} < {min_posts}"
        )

    potentials = [
        _num(post.get("potential"))
        for post in rows
    ]

    if model is not None:
        if history is None:
            history = _score_history(
                posts,
                audience,
                model,
            )
        _, model_scores, _ = history
        calibration_scores = model_scores
    else:
        calibration_scores = potentials

    sorted_calibration_scores = sorted(
        calibration_scores
    )

    mechanism_stats = {}
    combo_stats = {}

    for index, post in enumerate(rows):
        fit = _percentile_from_sorted(
            sorted_calibration_scores,
            calibration_scores[index],
        )

        mechanisms = sorted(
            set(post.get("mechanisms", []) or [])
        )

        for mechanism in mechanisms:
            mechanism_stats.setdefault(
                mechanism,
                [],
            ).append(fit)

        if len(mechanisms) >= 2:
            key = "+".join(mechanisms)
            combo_stats.setdefault(
                key,
                [],
            ).append(fit)

    mechanisms = {
        key: {
            "posts": len(values),
            "avg_fit": round(mean(values), 2),
            "median_fit": round(median(values), 2),
        }
        for key, values in mechanism_stats.items()
        if len(values) >= MIN_MECHANISM_POSTS
    }

    combinations = {
        key: {
            "posts": len(values),
            "avg_fit": round(mean(values), 2),
            "median_fit": round(median(values), 2),
        }
        for key, values in combo_stats.items()
        if len(values) >= MIN_MECHANISM_POSTS
    }

    return {
        "audience": audience,
        "posts": len(rows),
        "score_distribution": {
            "p10": round(_quantile(potentials, 0.10), 2),
            "p25": round(_quantile(potentials, 0.25), 2),
            "p50": round(_quantile(potentials, 0.50), 2),
            "p75": round(_quantile(potentials, 0.75), 2),
            "p90": round(_quantile(potentials, 0.90), 2),
            "mean": round(mean(potentials), 2),
            "median": round(median(potentials), 2),
            "min": round(min(potentials), 2),
            "max": round(max(potentials), 2),
        },
        "historical_potentials": [
            round(value, 4)
            for value in potentials
        ],
        "historical_model_scores": [
            round(value, 4)
            for value in calibration_scores
        ],
        "historical_model_scores_sorted": [
            round(value, 4)
            for value in sorted_calibration_scores
        ],
        "mechanisms": mechanisms,
        "combinations": combinations,
        "method": "within_audience_model_score_ecdf",
        "note": (
            "audience_fit — percentile свежего model score внутри "
            "собственной исторической шкалы аудитории. Raw score между "
            "аудиториями напрямую не сравнивается."
        ),
    }
def _affinity_features(post, content_types, mechanisms):
    """Compact interpretable feature vector for audience-affinity classifier."""
    values = []
    ct = post.get("content_type") or post.get("content_type_predicted") or "unknown"
    values.extend(1.0 if ct == item else 0.0 for item in content_types)
    used = set(post.get("mechanisms", []) or post.get("mechanisms_used", []) or [])
    values.extend(1.0 if m in used else 0.0 for m in mechanisms)
    numeric_names = (
        "mechanism_strength",
        "text_length",
        "has_media",
        "help_request",
        "complaint_signal",
        "advertising_signal",
        "opinion_signal",
        "question_cta",
        "emoji_count",
    )
    for name in numeric_names:
        value = post.get(name, 0.0)
        if isinstance(value, dict):
            value = 0.0
        try:
            values.append(float(value or 0.0))
        except (TypeError, ValueError):
            values.append(0.0)
    return values


def build_audience_affinity_model(posts, audiences=DEFAULT_AUDIENCES):
    """Train a small pure-Python logistic classifier for audience affinity.

    It predicts which audience historically published a post with similar
    structural/content features. This is an affinity signal, not a
    counterfactual performance model.
    """
    rows = [p for p in posts if p.get("audience") in audiences]
    if len(rows) < 200:
        return {"status": "insufficient_data", "posts": len(rows)}

    content_types = sorted({
        p.get("content_type") or "unknown" for p in rows
    })
    mechanisms = sorted({
        m for p in rows for m in (p.get("mechanisms", []) or [])
    })

    X = [
        _affinity_features(p, content_types, mechanisms)
        for p in rows
    ]
    y = [1.0 if p.get("audience") == audiences[1] else 0.0 for p in rows]
    n = len(X)
    dim = len(X[0])

    means = [sum(x[j] for x in X) / n for j in range(dim)]
    stds = []
    for j in range(dim):
        variance = sum((x[j] - means[j]) ** 2 for x in X) / n
        stds.append(math.sqrt(variance) or 1.0)

    Z = [[(x[j] - means[j]) / stds[j] for j in range(dim)] for x in X]
    weights = [0.0] * (dim + 1)
    learning_rate = 0.08
    regularization = 0.01
    epochs = 120

    for _ in range(epochs):
        grad = [0.0] * (dim + 1)
        for x, target in zip(Z, y):
            z = weights[0]
            for j in range(dim):
                z += weights[j + 1] * x[j]
            z = max(-30.0, min(30.0, z))
            probability = 1.0 / (1.0 + math.exp(-z))
            error = probability - target
            grad[0] += error
            for j in range(dim):
                grad[j + 1] += error * x[j]

        for j in range(dim + 1):
            penalty = regularization * weights[j] if j else 0.0
            weights[j] -= learning_rate * ((grad[j] / n) + penalty)

    return {
        "status": "ok",
        "method": "pure_python_logistic_regression",
        "posts": n,
        "audiences": list(audiences),
        "content_types": content_types,
        "mechanisms": mechanisms,
        "numeric_features": [
            "mechanism_strength",
            "text_length",
            "has_media",
            "help_request",
            "complaint_signal",
            "advertising_signal",
            "opinion_signal",
            "question_cta",
            "emoji_count",
        ],
        "means": [round(x, 8) for x in means],
        "stds": [round(x, 8) for x in stds],
        "weights": [round(x, 8) for x in weights],
        "epochs": epochs,
        "regularization": regularization,
        "note": (
            "Affinity классифицирует исторический тип публикации между "
            "аудиториями. Это не доказательство того, что публикация дала "
            "бы лучший результат в другой аудитории."
        ),
    }


def score_audience_affinity(post, model):
    if not model or model.get("status") != "ok":
        return {}

    audiences = model.get("audiences", list(DEFAULT_AUDIENCES))
    content_types = model.get("content_types", [])
    mechanisms = model.get("mechanisms", [])
    means = model.get("means", [])
    stds = model.get("stds", [])
    weights = model.get("weights", [])
    x = _affinity_features(post, content_types, mechanisms)

    z = weights[0]
    for j, value in enumerate(x):
        z += weights[j + 1] * ((value - means[j]) / (stds[j] or 1.0))
    z = max(-30.0, min(30.0, z))
    p_second = 1.0 / (1.0 + math.exp(-z))
    p_first = 1.0 - p_second

    return {
        audiences[0]: round(p_first * 100.0, 2),
        audiences[1]: round(p_second * 100.0, 2),
    }


def affinity_route(affinities, review_probability=60.0, both_margin=10.0, primary_margin=20.0):
    if len(affinities) < 2:
        return {"decision": "INSUFFICIENT_DATA", "best_audience": None, "second_audience": None, "margin": None}
    ordered = sorted(affinities.items(), key=lambda x: x[1], reverse=True)
    best, best_p = ordered[0]
    second, second_p = ordered[1]
    margin = round(best_p - second_p, 2)
    if best_p < review_probability:
        decision = "BOTH_OR_EDITORIAL_REVIEW"
    elif margin <= both_margin:
        decision = "BOTH"
    elif margin <= primary_margin:
        decision = f"{best}_PRIMARY_{second}_SECONDARY"
    else:
        decision = f"{best}_ONLY"
    return {
        "decision": decision,
        "best_audience": best,
        "second_audience": second,
        "margin": margin,
    }


def build_profiles(posts, models=None, audiences=DEFAULT_AUDIENCES):
    """Build profiles with one historical scoring pass per model."""
    models = models or {}
    profiles = {}

    for audience in audiences:
        model = models.get(audience)

        history = (
            _score_history(posts, audience, model)
            if model is not None
            else None
        )

        profile = build_audience_profile(
            posts,
            audience,
            model=model,
            history=history,
        )

        if history is not None:
            profile["score_calibration"] = (
                build_score_calibration(
                    posts,
                    audience,
                    model,
                    history=history,
                )
            )

        profiles[audience] = profile

    affinity_model = build_audience_affinity_model(
        posts,
        audiences=audiences,
    )

    return {
        "version": "3.1",
        "audiences": profiles,
        "audience_affinity_model": affinity_model,
        "router": {
            "low_margin": LOW_MARGIN,
            "high_margin": HIGH_MARGIN,
            "score_weight": 1.0,
            "mechanism_weight": 0.0,
            "status": "diagnostic_until_oos_validated",
        },
    }
def mechanism_fit(mechanisms, profile):
    """Диагностический средний fit по механизмам."""
    rows = []

    for mechanism in sorted(set(mechanisms or [])):
        item = profile.get("mechanisms", {}).get(mechanism)
        if item and item.get("posts", 0) >= MIN_MECHANISM_POSTS:
            rows.append(_num(item.get("avg_fit"), 50.0))

    if not rows:
        return None

    return round(mean(rows), 2)


def audience_fit(score, profile):
    """Return common-scale expected potential, not an audience-local percentile."""
    expected, density, method = calibrated_expected_potential(score, profile)
    return expected


def audience_percentile(score, profile):
    """Diagnostic percentile using cached sorted history."""
    history = profile.get(
        "historical_model_scores_sorted"
    ) or profile.get(
        "historical_potentials"
    ) or []

    return _percentile_from_sorted(
        history,
        score,
    )
def _word_number(text):
    """Return a Russian cardinal number from text, or None."""
    mapping = {
        "один": 1, "одна": 1, "одно": 1,
        "два": 2, "две": 2, "двое": 2,
        "три": 3, "трое": 3,
        "четыре": 4, "четверо": 4,
        "пять": 5, "пятеро": 5,
        "шесть": 6, "шестеро": 6,
        "семь": 7, "семеро": 7,
        "восемь": 8, "восьмеро": 8,
        "девять": 9, "девятеро": 9,
        "десять": 10,
    }
    for word, value in mapping.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            return value
    return None


def extract_event_meta(post, scored=None):
    """Extract the same event metadata for fresh scoring and OOS.

    Critical fix v2.4: classification.death_count may count occurrences of a
    word/phrase rather than the actual number of victims. For example,
    «погибли три человека» can otherwise become death_count=1. Here we parse
    explicit numeric victim counts and take the strongest supported value.
    """
    post = post or {}
    scored = scored or {}
    title = str(post.get("title") or "")
    body = str(post.get("text") or post.get("description") or "")
    text = f"{title} {body}".strip().lower()
    classification = scored.get("classification") if isinstance(scored, dict) else None
    classification = classification if isinstance(classification, dict) else {}

    death_count = int(_num(classification.get("death_count"), 0) or 0)

    # Digit forms: «3 человека погибли», «погибли 3 человека», «3 погибших».
    digit_patterns = (
        r"\b(\d{1,2})\s+(?:человек(?:а|ов)?|людей)\s+(?:погиб|умер|скончал)",
        r"\b(?:погиб|умер|скончал)\w*\s+(\d{1,2})\s+(?:человек(?:а|ов)?|людей)",
        r"\b(\d{1,2})\s+погибших\b",
        r"\b(?:погиб|умер|скончал)\w*\s+(\d{1,2})\b",
    )
    for pattern in digit_patterns:
        for match in re.finditer(pattern, text):
            death_count = max(death_count, int(match.group(1)))

    # Word-number forms: «погибли три человека», «погибло трое».
    death_verbs = r"(?:погиб\w*|умер\w*|скончал\w*)"
    number_words = r"(?:один|одна|одно|два|две|двое|три|трое|четыре|четверо|пять|пятеро|шесть|шестеро|семь|семеро|восемь|восьмеро|девять|девятеро|десять)"
    for match in re.finditer(rf"{death_verbs}[^.!?;:(){{}}]{{0,40}}\b({number_words})\b", text):
        word = match.group(1)
        value = _word_number(word)
        if value:
            death_count = max(death_count, value)
    for match in re.finditer(rf"\b({number_words})\b[^.!?;:(){{}}]{{0,25}}{death_verbs}", text):
        word = match.group(1)
        value = _word_number(word)
        if value:
            death_count = max(death_count, value)

    injury_hits = int(_num(classification.get("injury_hits"), 0) or 0)
    injury_hits = max(
        injury_hits,
        sum(
            len(re.findall(pattern, text))
            for pattern in (
                r"\bпострада\w*", r"\bтравм\w*", r"\bранен\w*",
                r"\bгоспитализ\w*", r"\bв больниц\w*", r"\bреанимац\w*",
            )
        ),
    )

    child_accident = bool(
        re.search(r"\bребён\w*|\bребен\w*|\bшкольник\w*|\bшкольниц\w*|\bмальчик\w*|\bдевочк\w*", text)
        and re.search(r"\bдтп\b|\bавари\w*|\bнаезд\w*|\bсбил\w*|\bсбила\w*|\bстолкнов\w*", text)
    )
    quarantine_disease = bool(
        re.search(r"\bкарантин\w*|\bограничен\w*", text)
        and re.search(r"\bболезн\w*|\bинфекц\w*|\bзаболев\w*|\bвирус\w*|\bэпидеми\w*|\bвспыш\w*", text)
    )
    pollution_environment = bool(
        re.search(r"\bртут\w*|\bпдк\b|\bзагрязн\w*|\bтоксич\w*|\bядовит\w*|\bотравлен\w*", text)
        and re.search(r"\bиртыш\w*|\bрек\w*|\bвод\w*|\bвоздух\w*|\bпочв\w*", text)
    )
    fire_multiple_injuries = bool(
        re.search(r"\bпожар\w*|\bзагорел\w*|\bвозгорани\w*", text)
        and injury_hits >= 2
    )

    # v2.5: broad-public topics may reasonably belong to both communities.
    public_both = bool(
        (
            re.search(r"\bшкол\w*|\bдет\w*|\bподрост\w*", text)
            and re.search(r"\bтабак\w*|\bвейп\w*|\bзапрет\w*", text)
        )
        or pollution_environment
        or (
            re.search(
                r"\bавтобус\w*|\bобщественн\w* транспорт|\bбезбилет\w*|\bзайц\w*",
                text,
            )
            and re.search(
                r"\bправил\w*|\bмер\w*|\bштраф\w*|\bоплат\w*|\bзапрет\w*|\bзаперт\w*",
                text,
            )
        )
    )

    advertising = bool(re.search(
        r"\bреклам\w*|\bскидк\w*|\bакци\w*|\bкупить\w*|\bзаказать\w*|\bмагазин\w*",
        text,
    ))

    hard_news_hint = bool(re.search(
        r"\bосуд\w*|\bхищен\w*|\bмошен\w*|\bмошеннич\w*|\bкраж\w*|"
        r"\bграбеж\w*|\bразбой\w*|\bуголовн\w*|\bарест\w*|"
        r"\bгибел\w*|\bтравм\w*|\bпогиб\w*|\bсмерт\w*|\bскончал\w*|\bумер\w*",
        text,
    ))

    return {
        "event_strength": _num(scored.get("fresh_event_strength"), _num(post.get("event_strength"), 0.0)),
        "death_count": death_count,
        "injury_hits": injury_hits,
        "child_accident": child_accident,
        "quarantine_disease": quarantine_disease,
        "pollution_environment": pollution_environment,
        "fire_multiple_injuries": fire_multiple_injuries,
        "public_both": public_both,
        "advertising": advertising,
        "hard_news_hint": hard_news_hint,
    }


def event_dominance_signal(post=None, event_strength=0.0, event_meta=None):
    """Return an interpretable event-dominance signal.

    The old v2.2 rule required event_strength >= 85, but the current
    fresh-event scale intentionally tops out much lower for several critical
    cases (for example a confirmed multi-fatality crash). We therefore use
    a hybrid rule: explicit severe event components + a moderate generic
    strength threshold.

    event_meta may be produced directly by analytics_core._fresh_event_strength
    or reconstructed from text.
    """
    meta = dict(event_meta or {})
    strength = max(0.0, min(100.0, _num(event_strength, 0.0)))

    if post is not None:
        parsed_meta = extract_event_meta(post, {"fresh_event_strength": strength})
        for key, value in parsed_meta.items():
            if key == "event_strength":
                continue
            if key in ("death_count", "injury_hits"):
                meta[key] = max(int(_num(meta.get(key), 0) or 0), int(_num(value, 0) or 0))
            elif value:
                meta[key] = value
        title = str(post.get("title") or "")
        body = str(post.get("text") or post.get("description") or "")
        text = f"{title} {body}".lower()

        meta.setdefault("death_count", sum(
            len(re.findall(pattern, text))
            for pattern in (
                r"\bпогиб\w*", r"\bумер\w*",
                r"\bскончал\w*", r"\bсмерт\w*",
            )
        ))
        meta.setdefault("injury_hits", sum(
            len(re.findall(pattern, text))
            for pattern in (
                r"\bпострада\w*", r"\bтравм\w*",
                r"\bранен\w*", r"\bгоспитализ\w*",
                r"\bв больниц\w*", r"\bреанимац\w*",
            )
        ))
        meta.setdefault("child_accident", bool(
            re.search(
                r"\bребён\w*|\bребен\w*|\bшкольник\w*|"
                r"\bшкольниц\w*|\bмальчик\w*|\bдевочк\w*",
                text,
            )
            and re.search(
                r"\bдтп\b|\bавари\w*|\bнаезд\w*|"
                r"\bсбил\w*|\bсбила\w*|\bстолкнов\w*",
                text,
            )
        ))
        meta.setdefault("quarantine_disease", bool(
            re.search(r"\bкарантин\w*|\bограничен\w*", text)
            and re.search(
                r"\bболезн\w*|\bинфекц\w*|\bзаболев\w*|"
                r"\bвирус\w*|\bэпидеми\w*|\bвспыш\w*",
                text,
            )
        ))
        meta.setdefault("pollution_environment", bool(
            re.search(
                r"\bртут\w*|\bпдк\b|\bзагрязн\w*|\bтоксич\w*|"
                r"\bядовит\w*|\bотравлен\w*", text,
            )
            and re.search(
                r"\bиртыш\w*|\bрек\w*|\bвод\w*|"
                r"\bвоздух\w*|\bпочв\w*", text,
            )
        ))
        meta.setdefault("fire_multiple_injuries", bool(
            re.search(r"\bпожар\w*|\bзагорел\w*|\bвозгорани\w*", text)
            and int(meta.get("injury_hits", 0) or 0) >= 2
        ))

    deaths = int(_num(meta.get("death_count"), 0))
    injuries = int(_num(meta.get("injury_hits"), 0))
    child_accident = bool(meta.get("child_accident"))
    quarantine_disease = bool(meta.get("quarantine_disease"))
    pollution_environment = bool(meta.get("pollution_environment"))
    fire_multiple_injuries = bool(meta.get("fire_multiple_injuries"))

    reasons = []
    level = 0

    if deaths >= 3:
        level = max(level, 3)
        reasons.append("3+ deaths")
    elif deaths >= 2:
        level = max(level, 2)
        reasons.append("2 deaths")
    elif deaths >= 1:
        level = max(level, 1)
        reasons.append("death")

    if child_accident and strength >= 40:
        level = max(level, 2)
        reasons.append("child+accident")

    if quarantine_disease and strength >= 40:
        level = max(level, 2)
        reasons.append("quarantine+disease")

    if pollution_environment and strength >= 45:
        level = max(level, 2)
        reasons.append("pollution+environment")

    if fire_multiple_injuries and strength >= 40:
        level = max(level, 2)
        reasons.append("fire+multiple injuries")

    if strength >= 70:
        level = max(level, 2)
        reasons.append("event_strength>=70")

    return {
        "dominant": level > 0,
        "level": level,
        "reasons": reasons,
        "event_strength": round(strength, 2),
        "death_count": deaths,
        "injury_hits": injuries,
    }

def route_scores(
    audience_scores,
    profiles,
    mechanisms=None,
    affinity=None,
    event_strength=0.0,
    event_meta=None,
    low_margin=3.0,
    high_margin=8.0,
    performance_weight=0.60,
    affinity_weight=0.40,
    priority_threshold=62.0,
    take_threshold=55.0,
    reserve_threshold=52.0,
):
    """Единый router для fresh и OOS с редакторскими предохранителями."""
    if abs((performance_weight + affinity_weight) - 1.0) > 1e-9:
        raise ValueError("performance_weight + affinity_weight must equal 1.0")

    expected = {}
    percentiles = {}
    mechanism_fits = {}
    calibration_meta = {}
    affinity = affinity or {}
    utility = {}

    for audience, score in audience_scores.items():
        profile = profiles.get(audience, {})
        expected_value, density, method = calibrated_expected_potential(score, profile)
        expected[audience] = round(expected_value, 2)
        percentiles[audience] = audience_percentile(score, profile)
        mechanism_fits[audience] = mechanism_fit(mechanisms, profile)
        calibration_meta[audience] = {
            "expected_potential": round(expected_value, 2),
            "score_percentile_within_audience": percentiles[audience],
            "calibration_density": density,
            "calibration_method": method,
            "affinity_prior": round(_num(affinity.get(audience), 50.0), 2),
        }
        utility[audience] = round(
            expected_value * performance_weight
            + _num(affinity.get(audience), 50.0) * affinity_weight,
            2,
        )

    ordered = sorted(utility.items(), key=lambda item: item[1], reverse=True)
    event_strength = max(0.0, min(100.0, _num(event_strength, 0.0)))
    dominance = event_dominance_signal(
        post=None,
        event_strength=event_strength,
        event_meta=event_meta,
    )

    event_meta = event_meta or {}
    public_both = bool(event_meta.get("public_both"))
    advertising = bool(event_meta.get("advertising"))

    if len(ordered) < 2:
        return {
            "fits": utility,
            "expected_potential": expected,
            "percentiles": percentiles,
            "mechanism_fits": mechanism_fits,
            "calibration": calibration_meta,
            "best_audience": ordered[0][0] if ordered else None,
            "second_audience": None,
            "fit_margin": None,
            "decision": "INSUFFICIENT_DATA",
            "method": "calibrated_performance_60_affinity_prior_40_v2_5",
            "weights": {"performance": performance_weight, "affinity": affinity_weight},
            "event_strength": round(event_strength, 2),
            "event_dominant": bool(dominance.get("dominant")),
            "event_dominance": dominance,
            "public_both": public_both,
            "advertising": advertising,
        }

    best_audience, best_fit = ordered[0]
    second_audience, second_fit = ordered[1]
    margin = round(best_fit - second_fit, 2)

    score_status = {}
    status_rank = {"ПРОПУСК": 0, "РЕЗЕРВ": 1, "ВЗЯТЬ": 2, "ПРИОРИТЕТ": 3}
    for audience, score in audience_scores.items():
        s = _num(score, 0.0)
        if s >= priority_threshold:
            score_status[audience] = "ПРИОРИТЕТ"
        elif s >= take_threshold:
            score_status[audience] = "ВЗЯТЬ"
        elif s >= reserve_threshold:
            score_status[audience] = "РЕЗЕРВ"
        else:
            score_status[audience] = "ПРОПУСК"

    # 1. Commercial/ad content should not be routed as editorial news.
    if advertising:
        decision = "SKIP_OR_EDITORIAL_REVIEW"
        best_audience = None
        second_audience = None

    # 2. Broad public-interest stories can legitimately be used by both pages.
    elif public_both:
        decision = "BOTH"

    # 3. Severe events are primary/secondary rather than forced into one page.
    elif bool(dominance.get("dominant")):
        decision = f"{best_audience}_PRIMARY_{second_audience}_SECONDARY"

    else:
        best_status = score_status.get(best_audience, "ПРОПУСК")
        second_status = score_status.get(second_audience, "ПРОПУСК")
        hard_news_hint = bool(event_meta.get("hard_news_hint"))

        # 4. Hard-news topics bypass the generic status tie-breaker:
        # the audience utility is allowed to select Zhest even when its
        # raw editorial score is lower because the historical scale differs.
        if hard_news_hint:
            if best_fit < 48.0:
                decision = "SKIP_OR_EDITORIAL_REVIEW"
            elif margin <= low_margin:
                decision = "BOTH"
            elif margin <= high_margin:
                decision = f"{best_audience}_PRIMARY_{second_audience}_SECONDARY"
            else:
                decision = f"{best_audience}_ONLY"
        # 5. For ordinary stories, if only one audience has meaningful
        # editorial priority/take status, preserve that broad signal.
        elif status_rank[best_status] > status_rank[second_status] and status_rank[best_status] >= 2:
            decision = f"{best_audience}_ONLY"
        elif status_rank[second_status] > status_rank[best_status] and status_rank[second_status] >= 2:
            decision = f"{second_audience}_ONLY"
            best_audience, second_audience = second_audience, best_audience
        elif best_fit < 48.0:
            decision = "SKIP_OR_EDITORIAL_REVIEW"
        elif margin <= low_margin:
            decision = "BOTH"
        elif margin <= high_margin:
            decision = f"{best_audience}_PRIMARY_{second_audience}_SECONDARY"
        else:
            decision = f"{best_audience}_ONLY"

    return {
        "fits": {k: round(v, 2) for k, v in utility.items()},
        "expected_potential": expected,
        "percentiles": percentiles,
        "mechanism_fits": mechanism_fits,
        "calibration": calibration_meta,
        "best_audience": best_audience,
        "second_audience": second_audience,
        "fit_margin": margin,
        "event_strength": round(event_strength, 2),
        "event_dominant": bool(dominance.get("dominant")),
        "event_dominance": dominance,
        "public_both": public_both,
        "advertising": advertising,
        "hard_news_hint": bool(event_meta.get("hard_news_hint")),
        "score_status": score_status,
        "decision": decision,
        "method": "calibrated_performance_60_affinity_prior_40_v2_5",
        "weights": {"performance": performance_weight, "affinity": affinity_weight},
    }


def _split_chronological(posts, periods=4):
    """Split each audience on its own timeline, then align period indices.

    This is essential for multi-audience data: one group may have a different
    history window than another, so a single global timestamp split can leave
    an entire training fold without one audience.
    """
    by_audience = {}
    for post in posts:
        by_audience.setdefault(post.get("audience"), []).append(post)

    chunks_by_audience = {}
    for audience, rows in by_audience.items():
        ordered = sorted(rows, key=lambda p: float(p.get("timestamp", 0) or 0))
        n = len(ordered)
        if n < periods:
            return []
        base = max(1, n // periods)
        chunks = []
        start = 0
        for i in range(periods):
            end = n if i == periods - 1 else min(n, start + base)
            chunks.append(ordered[start:end])
            start = end
        chunks_by_audience[audience] = chunks

    if not chunks_by_audience:
        return []

    return [
        [post for audience_chunks in chunks_by_audience.values()
         for post in audience_chunks[i]]
        for i in range(periods)
    ]


def _build_model_for_training(train_rows, audience):
    """Build an audience model using training history only."""
    from lib.analytics_core import (
        build_editorial_model_v1,
        mechanism_report,
        temporal_oos_combination_validation,
    )
    mechanisms = list(__import__("lib.analytics_core", fromlist=["MECHANISM_RULES"]).MECHANISM_RULES.keys())
    rows = [p for p in train_rows if p.get("audience") == audience]
    if len(rows) < MIN_PROFILE_POSTS:
        return None
    report = mechanism_report(rows)
    temporal = temporal_oos_combination_validation(
        rows,
        mechanisms,
        periods=4,
        top_n_train=30,
        min_train_posts=8,
        min_test_posts=3,
        min_periods_present=2,
    )
    model = build_editorial_model_v1(rows, report, temporal)
    model["audience"] = audience
    return model


def _build_training_profile(train_rows, audience, model):
    """Profile built only from the chronological training window."""
    return build_audience_profile(
        train_rows,
        audience,
        model=model,
        min_posts=MIN_PROFILE_POSTS,
    )


def chronological_routing_oos(posts, audiences=DEFAULT_AUDIENCES, periods=4):
    """Chronological OOS of the *actual production routing algorithm*.

    Training creates one editorial model + calibration profile per audience.
    Test posts are scored by both models, mapped to the common observed-
    potential scale, and passed through route_scores(). No affinity classifier
    participates in the decision.

    This remains an observed-audience-alignment test, not a counterfactual
    causal test: historical posts normally appeared in only one community.
    """
    chunks = _split_chronological(posts, periods=periods)
    if len(chunks) < 2:
        return {
            "method": "chronological_common_scale_routing",
            "status": "insufficient_data",
            "production_ready": False,
            "splits": [],
        }

    split_results = []
    all_rows = []

    from lib.analytics_core import score_fresh_post

    for test_idx in range(1, len(chunks)):
        train_rows = [p for c in chunks[:test_idx] for p in c]
        test_rows = chunks[test_idx]

        affinity_model = build_audience_affinity_model(train_rows, audiences=audiences)

        models = {}
        profiles = {}
        for audience in audiences:
            model = _build_model_for_training(train_rows, audience)
            if model is None:
                continue
            models[audience] = model
            profiles[audience] = _build_training_profile(train_rows, audience, model)

        if len(models) < len(audiences):
            split_results.append({
                "test_period": test_idx + 1,
                "status": "insufficient_training_history",
                "train_posts": len(train_rows),
                "test_posts": len(test_rows),
            })
            continue

        rows = []
        for post in test_rows:
            scores = {}
            mechanisms = post.get("mechanisms", []) or []
            event_meta = {}
            scored_reference = {}
            for audience in audiences:
                scored = score_fresh_post(post, models[audience])
                scores[audience] = _num(scored.get("potential_score"), 0.0)
                scored_reference = scored
                if not mechanisms:
                    mechanisms = scored.get("mechanisms_used", []) or []

                if not event_meta and isinstance(scored.get("fresh_event_strength"), (int, float)):
                    event_meta = {
                        "event_strength": _num(scored.get("fresh_event_strength"), 0.0),
                    }
                classification = scored.get("classification") or {}
                if not event_meta.get("death_count") and classification:
                    event_meta["death_count"] = _num(classification.get("death_count"), 0)

            event_meta = extract_event_meta(post, scored_reference)
            event_strength = _num(event_meta.get("event_strength"), 0.0)

            affinity_post = dict(post)
            affinity_post["mechanisms"] = mechanisms
            affinity_post["mechanisms_used"] = mechanisms
            affinity_post["mechanism_strength"] = scored_reference.get("mechanism_strength")
            affinity_post["content_type"] = scored_reference.get("content_type") or affinity_post.get("content_type")
            affinity = score_audience_affinity(affinity_post, affinity_model)

            routed = route_scores(
                scores, profiles, mechanisms, affinity=affinity,
                event_strength=event_strength,
                event_meta=event_meta,
            )
            actual = post.get("audience")
            best = routed.get("best_audience")
            eligible = bool(best)
            aligned = bool(eligible and best == actual)
            row = {
                "post_id": post.get("post_id"),
                "actual_audience": actual,
                "best_audience": best,
                "decision": routed.get("decision"),
                "fit_margin": routed.get("fit_margin"),
                "event_strength": routed.get("event_strength", event_strength),
                "event_dominant": routed.get("event_dominant", False),
                "event_dominance": routed.get("event_dominance", {}),
                "fits": routed.get("fits", {}),
                "raw_scores": scores,
                "affinity": affinity,
                "actual_potential": _num(post.get("potential")),
                "aligned": aligned,
                "eligible": eligible,
            }
            rows.append(row)
            all_rows.append(row)

        eligible_rows = [r for r in rows if r["eligible"]]
        aligned_rows = [r for r in eligible_rows if r["aligned"]]
        split_results.append({
            "test_period": test_idx + 1,
            "status": "ok",
            "train_posts": len(train_rows),
            "test_posts": len(test_rows),
            "eligible_posts": len(eligible_rows),
            "coverage": round(len(eligible_rows) / len(rows), 3) if rows else 0.0,
            "alignment": round(len(aligned_rows) / len(eligible_rows), 3) if eligible_rows else None,
            "golos_recall": round(
                sum(1 for r in eligible_rows if r["actual_audience"] == "golos" and r["best_audience"] == "golos") /
                max(1, sum(1 for r in eligible_rows if r["actual_audience"] == "golos")), 3
            ),
            "zhest_recall": round(
                sum(1 for r in eligible_rows if r["actual_audience"] == "zhest" and r["best_audience"] == "zhest") /
                max(1, sum(1 for r in eligible_rows if r["actual_audience"] == "zhest")), 3
            ),
        })

    ok_splits = [s for s in split_results if s.get("status") == "ok"]
    eligible = [r for r in all_rows if r["eligible"]]
    aligned = [r for r in eligible if r["aligned"]]
    actual_counts = {a: sum(1 for r in eligible if r["actual_audience"] == a) for a in audiences}
    majority = max(actual_counts.values(), default=0) / max(1, len(eligible))
    alignment = len(aligned) / max(1, len(eligible))
    coverage = len(eligible) / max(1, len(all_rows))

    min_golos_recall = min((s.get("golos_recall", 0.0) for s in ok_splits), default=0.0)
    min_zhest_recall = min((s.get("zhest_recall", 0.0) for s in ok_splits), default=0.0)
    production_ready = bool(
        len(ok_splits) >= 2
        and coverage >= 0.80
        and alignment >= max(0.60, majority + 0.05)
        and min_golos_recall >= 0.50
        and min_zhest_recall >= 0.50
        and all(s.get("alignment") is not None for s in ok_splits)
    )

    return {
        "method": "chronological_common_scale_routing",
        "status": "ok" if ok_splits else "insufficient_splits",
        "periods": len(chunks),
        "splits": split_results,
        "posts_tested": len(all_rows),
        "eligible_posts": len(eligible),
        "coverage": round(coverage, 3),
        "observed_audience_alignment": round(alignment, 3),
        "majority_baseline": round(majority, 3),
        "lift_vs_majority_baseline": round(alignment - majority, 3),
        "production_ready": production_ready,
        "status_for_production": "DIAGNOSTIC_ONLY",
        "routing_algorithm": "model_score -> expected_observed_potential + affinity_prior -> route_scores",
        "routing_weights": {"performance": 0.60, "affinity": 0.40},
        "event_dominance": {
            "threshold": 85.0,
            "action": "best_primary_second_secondary",
        },
        "minimum_per_audience_recall": 0.50,
        "critical_limit": (
            "Исторический VK-датасет не содержит контрфактических результатов. "
            "OOS измеряет совпадение с фактической аудиторией, но не доказывает, "
            "что другая аудитория дала бы худший или лучший результат."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

