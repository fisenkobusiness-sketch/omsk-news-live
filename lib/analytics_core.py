# -*- coding: utf-8 -*-
"""Общая библиотека аналитики. Не обращается к VK."""

from bisect import bisect_left, bisect_right
import csv
import itertools
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def safe_rate(value, denominator):
    if not denominator:
        return 0.0
    return float(value) / float(denominator)


def _percentile_sorted(sorted_values, value):
    """Percentile for an already sorted sequence."""
    if not sorted_values:
        return 0.0

    n = len(sorted_values)
    if n == 1:
        return 100.0

    value = float(value)
    left = bisect_left(sorted_values, value)
    right = bisect_right(sorted_values, value)
    equal = right - left

    rank = left + (equal - 1) / 2.0
    return rank / (n - 1) * 100.0


def percentile(values, value):
    """Percentile 0..100 with historical tie handling."""
    if not values:
        return 0.0
    return _percentile_sorted(
        sorted(float(v) for v in values),
        value,
    )
def robust_log(value):
    return math.log1p(max(0.0, float(value)))


def add_basic_metrics(posts):
    now = time.time()

    for post in posts:
        views = post["views"]
        likes = post["likes"]
        comments = post["comments"]
        reposts = post["reposts"]

        age_hours = max(
            0.25,
            (now - post["timestamp"]) / 3600.0,
        )

        post["age_hours"] = round(age_hours, 2)

        post["like_rate"] = safe_rate(likes, views)
        post["comment_rate"] = safe_rate(comments, views)
        post["repost_rate"] = safe_rate(reposts, views)

        # Comments are retained as discussion signal.
        # They are not treated as positive approval by themselves.
        post["engagement_rate"] = safe_rate(
            likes + comments * 2 + reposts * 4,
            views,
        )

        post["views_per_hour"] = safe_rate(views, age_hours)

        post["log_views"] = round(robust_log(views), 4)
        post["log_reposts"] = round(robust_log(reposts), 4)
        post["log_likes"] = round(robust_log(likes), 4)


# ============================================================
# BUILT-IN CONTENT / MECHANISM CLASSIFIER
# ============================================================
# The classifier deliberately produces interpretable audience
# mechanisms rather than pretending to be an ML model.
# A post can have several mechanisms at the same time.

MECHANISM_RULES = {
    "locality": (
        "омск", "омской", "омская", "омское", "омск", "омич",
        "омичи", "район", "округ", "улиц", "проспект", "площад",
        "набережн", "иртыш", "омка", "область",
    ),
    "incident": (
        "дтп", "авар", "пожар", "взрыв", "погиб", "погибла",
        "умер", "умерла", "пропал", "пропала", "пропали",
        "задерж", "напал", "напали", "избил", "избили",
        "сбил", "сбила", "наезд", "столкнов", "криминал",
        "тело", "спасател", "чп", "происшеств",
        "гибел", "травм", "осуд", "хищен", "мошен",
        "мошеннич", "краж", "грабеж", "разбой", "уголовн",
        "арест", "беспилот", "бпла", "давк",
    ),
    "conflict": (
        "скандал", "конфликт", "разгорел", "возмущ", "жалоб",
        "претенз", "требуют", "требован", "спор", "разруг",
        "избил", "драка", "кошмар", "бесит", "безобраз",
        "наруш", "не выплат", "не заплат", "проблем",
    ),
    "human_story": (
        "мужчин", "женщин", "мужчина", "женщина", "ребен",
        "малыш", "мама", "мам", "пап", "семь", "семьей",
        "семьёй", "пенсион", "волонтер", "волонтёр", "герой",
        "спортсмен", "врач", "медик", "водител", "жител",
        "омич", "сосед",
    ),
    "animal": (
        "медвед", "собак", "пёс", "пес", "кот", "кошк", "котят",
        "борз", "щен", "животн", "лошад", "птиц", "голуб",
        "мыш", "звер", "лис", "барханн",
    ),
    "weather": (
        "снег", "снегопад", "дожд", "ливн", "град", "ветер",
        "шторм", "циклон", "похолод", "потепл", "жар", "мороз",
        "температур", "непогод", "гроза", "метел", "гололед",
        "гололёд", "сияни", "метеор",
    ),
    "unusual": (
        "необыч", "редк", "впервые", "первый", "первыe", "странн",
        "удив", "шок", "аномал", "нлo", "нло", "засняли",
        "заметили", "случайн", "неожидан", "гигант", "огромн",
        "светящ", "аномаль",
    ),
    "humor": (
        "😂", "😅", "🤣", "😄", "😆", "😁", "😜", "😎",
        "шут", "смешн", "забав", "юмор", "прикол", "хохм",
        "как вам", "признавайтесь",
    ),
    "shock": (
        "😱", "‼", "шок", "ужас", "кошмар", "жутк", "страшн",
        "вопиющ", "трагед", "катастроф", "живьем", "заживо",
        "опасн", "смерт", "погиб", "убий",
    ),
    "fear": (
        "опасн", "страшн", "угроз", "тревог", "паник", "боят",
        "страх", "шанс погиб", "может погиб", "осторож",
    ),
    "positive_emotion": (
        "😍", "🥰", "❤️", "❤", "😊", "😄", "😁", "🤩", "👍",
        "добр", "уют", "радост", "счаст", "любов", "красив",
        "празднич", "душевн", "герой", "молодец",
    ),
    "usefulness": (
        "важн", "внимани", "предупрежд", "правил", "запрет",
        "разреш", "штраф", "измен", "расписан", "цена",
        "провер", "сирен", "перенес",
        "тариф", "оплат", "перекры", "ограничен", "можно",
        "нельзя", "что делать", "как",
    ),
    "help_request": (
        "помогите", "помогите найти", "разыскиваем", "ищем",
        "кто видел", "нужна помощь", "нужны доноры", "откликнитесь",
        "пожалуйста, опубликуйте", "потерялся", "потерялась",
    ),
    "visual_hook": (
        "фото", "фотограф", "сняли", "снято", "видео", "ролик",
        "кадры", "засняли", "видно", "посмотрите", "выглядит",
    ),
}

AD_WORDS = (
    "реклама", "купить", "заказать", "скидка", "акция",
    "магазин", "услуги", "продам", "продается", "продаём",
)

OPINION_WORDS = (
    "как вам", "что думаете", "ваше мнение", "согласны",
    "опрос", "мнение", "считаете", "признавайтесь",
)

QUESTION_RE = re.compile(r"[?？]")
EMOJI_RE = re.compile(
    "[\\U0001F300-\\U0001FAFF\\U00002600-\\U000027BF]"
)

ANIMAL_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bмедвед\w*",
        r"\bсобак\w*",
        r"\bпёс\w*",
        r"\bпес(?:ом|у|а|ы|е|ей|ем)?\b",
        r"\bкот(?:а|у|ом|е|ы|ов|ам|ами|ах)?\b",
        r"\bкошк\w*",
        r"\bкотят\w*",
        r"\bборз\w*",
        r"\bщен(?:ок|ка|ку|ком|ке|ки|ков|кам|ками|ках)?\b",
        r"\bживотн\w*",
        r"\bлошад\w*",
        r"\bптиц\w*",
        r"\bголуб\w*",
        r"\bмыш(?:ь|и|ей|ью|ам|ами|ах)?\b",
        r"\bзвер\w*",
        r"\bлис(?:а|ы|у|ой|ом|е|ов|ам|ами|ах)?\b",
        r"\bбарханн\w*",
    )
)

OFFICIAL_ATTRIBUTION_RE = re.compile(
    r"\b(официальн|МЧС|МВД|ГИБДД|Роспотребнадзор|"
    r"правительств|губернатор|администрац|минздрав|"
    r"прокуратур|следственн)\w*",
    re.IGNORECASE,
)


def _contains_marker(text, marker):
    """Match Russian lexical markers without substring false positives."""
    marker = str(marker or '').strip().lower()
    if not marker:
        return False

    if " " in marker or marker.endswith("-"):
        return marker in text

    if len(marker) <= 4:
        return bool(re.search(rf'(?<![а-яёa-z]){re.escape(marker)}(?![а-яёa-z])', text))

    return bool(re.search(
        rf'(?<![а-яёa-z]){re.escape(marker)}[а-яёa-zё-]*',
        text,
    ))


def contains_any(text, words):
    return any(_contains_marker(text, word) for word in words)


def classify_one(post):
    title = (post.get("title") or "").strip()
    body = (post.get("text") or "").strip()
    text = " ".join(part for part in (title, body) if part).strip()
    lower = text.lower()

    mechanisms = []
    scores = {}

    for mechanism, words in MECHANISM_RULES.items():
        # v2.7: animal — только по отдельным лексемам животных.
        # Важно: обычный substring-match даёт ложные срабатывания:
        # "щен" -> "проверку ... пройдет", "лис" -> "пассажир ...",
        # "кот" -> "которая", "щен" -> "решение".
        if mechanism == "animal":
            hits = sum(
                1 for pattern in ANIMAL_PATTERNS
                if pattern.search(lower)
            )
        else:
            hits = sum(1 for word in words if _contains_marker(lower, word))

        if hits:
            mechanisms.append(mechanism)
            scores[mechanism] = min(1.0, 0.25 + hits * 0.15)

    # Advertising requires a stronger signal than a generic commercial noun.
    # Words like "магазин" can describe an ordinary news event and must not
    # classify the whole story as advertising on their own.
    ad_matches = [
        word for word in AD_WORDS
        if _contains_marker(lower, word)
    ]
    strong_ad_matches = [
        word for word in ad_matches
        if word not in {"магазин", "услуги"}
    ]
    advertising_signal = bool(
        strong_ad_matches
        or len(ad_matches) >= 2
    )

    if advertising_signal:
        content_type = "advertising"
    elif "help_request" in mechanisms:
        content_type = "help_request"
        advertising_signal = False
    elif "incident" in mechanisms:
        content_type = "incident"
        advertising_signal = False
    elif "conflict" in mechanisms:
        content_type = "complaint"
        advertising_signal = False
    elif "opinion" in mechanisms:
        content_type = "opinion"
        advertising_signal = False
    elif "animal" in mechanisms or "human_story" in mechanisms:
        content_type = "social_story"
        advertising_signal = False
    elif not text:
        content_type = "visual"
        advertising_signal = False
    else:
        content_type = "news"
        advertising_signal = False

    question_signal = bool(QUESTION_RE.search(text))
    emoji_count = len(EMOJI_RE.findall(text))

    # A simple structural description of the post.
    if question_signal:
        mechanisms.append("question_cta")

    if emoji_count:
        mechanisms.append("emoji_hook")

    if post.get("attachment_count", 0):
        mechanisms.append("media")

    # "Official" is intentionally conservative: we only mark explicit
    # official wording, not inferred authority.
    official_attribution = bool(
        OFFICIAL_ATTRIBUTION_RE.search(lower)
    )

    # Lightweight confidence of the classification itself.
    confidence = min(
        0.95,
        0.30
        + min(0.30, len(mechanisms) * 0.05)
        + (0.15 if len(text) >= 80 else 0)
        + (0.10 if content_type != "news" else 0),
    )

    result = {
        "content_type": content_type,
        "classification_confidence": round(confidence, 3),
        "mechanisms": sorted(set(mechanisms)),
        "mechanism_strength": {
            k: round(v, 3) for k, v in scores.items()
        },
        "official_attribution": official_attribution,
        "help_request": "help_request" in mechanisms,
        "complaint_signal": "conflict" in mechanisms,
        "advertising_signal": advertising_signal,
        "opinion_signal": question_signal,
        "question_cta": question_signal,
        "emoji_count": emoji_count,
        "text_length": len(text),
        "has_media": bool(post.get("attachment_count", 0)),
    }

    return result


def classify_posts(posts):
    for post in posts:
        post.update(classify_one(post))


# ============================================================
# SCORES
# ============================================================

def calculate_scores(posts):
    """Calculate historical scores with one sort per metric."""
    if not posts:
        return

    repost_rates = sorted(
        float(p["repost_rate"]) for p in posts
    )
    engagement_rates = sorted(
        float(p["engagement_rate"]) for p in posts
    )
    like_rates = sorted(
        float(p["like_rate"]) for p in posts
    )
    views_velocity = sorted(
        float(p["views_per_hour"]) for p in posts
    )

    for post in posts:
        repost_pct = _percentile_sorted(
            repost_rates,
            post["repost_rate"],
        )
        engagement_pct = _percentile_sorted(
            engagement_rates,
            post["engagement_rate"],
        )
        like_pct = _percentile_sorted(
            like_rates,
            post["like_rate"],
        )
        velocity_pct = _percentile_sorted(
            views_velocity,
            post["views_per_hour"],
        )

        viral = (
            repost_pct * 0.60
            + engagement_pct * 0.25
            + velocity_pct * 0.15
        )
        approval = (
            like_pct * 0.75
            + engagement_pct * 0.25
        )
        potential = (
            viral * 0.60
            + approval * 0.40
        )

        post["virality"] = round(
            max(0.0, min(100.0, viral)),
            2,
        )
        post["approval"] = round(
            max(0.0, min(100.0, approval)),
            2,
        )
        post["potential"] = round(
            max(0.0, min(100.0, potential)),
            2,
        )

        post["repost_percentile"] = round(
            repost_pct,
            2,
        )
        post["like_percentile"] = round(
            like_pct,
            2,
        )
        post["velocity_percentile"] = round(
            velocity_pct,
            2,
        )
        post["engagement_percentile"] = round(
            engagement_pct,
            2,
        )

        views = max(
            0.0,
            float(post.get("views", 0)),
        )
        confidence = 1.0 - math.exp(
            -views / 5000.0
        )
        post["metric_confidence"] = round(
            confidence,
            3,
        )
        post["confidence_adjusted_potential"] = round(
            post["potential"] * confidence,
            2,
        )
def content_type_report(posts):
    result = {}

    for post in posts:
        content_type = post.get("content_type", "unknown")

        bucket = result.setdefault(
            content_type,
            {
                "posts": 0,
                "avg_virality": 0.0,
                "avg_approval": 0.0,
                "avg_potential": 0.0,
                "avg_reposts": 0.0,
                "avg_likes": 0.0,
                "avg_comments": 0.0,
                "avg_views": 0.0,
            },
        )

        bucket["posts"] += 1
        bucket["avg_virality"] += post.get("virality", 0)
        bucket["avg_approval"] += post.get("approval", 0)
        bucket["avg_potential"] += post.get("potential", 0)
        bucket["avg_reposts"] += post["reposts"]
        bucket["avg_likes"] += post["likes"]
        bucket["avg_comments"] += post["comments"]
        bucket["avg_views"] += post["views"]

    for bucket in result.values():
        n = bucket["posts"]
        if not n:
            continue

        for key in (
            "avg_virality",
            "avg_approval",
            "avg_potential",
            "avg_reposts",
            "avg_likes",
            "avg_comments",
            "avg_views",
        ):
            bucket[key] = round(bucket[key] / n, 2)

    return result


def compact_post(post):
    return {
        "post_id": post["post_id"],
        "date": post["date"],
        "text": post["text"][:500],
        "views": post["views"],
        "reposts": post["reposts"],
        "likes": post["likes"],
        "comments": post["comments"],
        "virality": post["virality"],
        "approval": post["approval"],
        "potential": post["potential"],
        "content_type": post.get("content_type", "unknown"),
        "mechanisms": post.get("mechanisms", []),
        "metric_confidence": post.get("metric_confidence", 0),
        "confidence_adjusted_potential": post.get(
            "confidence_adjusted_potential", 0
        ),
        "url": post["url"],
    }



def mechanism_report(posts):
    result = {}

    for post in posts:
        mechanisms = post.get("mechanisms", [])
        for mechanism in mechanisms:
            bucket = result.setdefault(
                mechanism,
                {
                    "posts": 0,
                    "avg_virality": 0.0,
                    "avg_approval": 0.0,
                    "avg_potential": 0.0,
                    "avg_confidence_adjusted_potential": 0.0,
                    "avg_views": 0.0,
                    "avg_reposts": 0.0,
                    "avg_likes": 0.0,
                },
            )

            bucket["posts"] += 1
            bucket["avg_virality"] += post.get("virality", 0)
            bucket["avg_approval"] += post.get("approval", 0)
            bucket["avg_potential"] += post.get("potential", 0)
            bucket["avg_confidence_adjusted_potential"] += post.get(
                "confidence_adjusted_potential", 0
            )
            bucket["avg_views"] += post.get("views", 0)
            bucket["avg_reposts"] += post.get("reposts", 0)
            bucket["avg_likes"] += post.get("likes", 0)

    for bucket in result.values():
        n = bucket["posts"]
        for key in (
            "avg_virality",
            "avg_approval",
            "avg_potential",
            "avg_confidence_adjusted_potential",
            "avg_views",
            "avg_reposts",
            "avg_likes",
        ):
            bucket[key] = round(bucket[key] / n, 2)

    return dict(
        sorted(
            result.items(),
            key=lambda kv: kv[1]["avg_confidence_adjusted_potential"],
            reverse=True,
        )
    )


def mechanism_combinations(posts, mechanisms, min_posts=20, top_n=100):
    """Analyze mechanism pairs/triples with streaming aggregates.

    The previous implementation kept one score dict per post per
    combination. We only need counts and sums, so aggregating in one pass
    reduces both memory usage and Python-level work.
    """
    allowed = set(mechanisms or [])
    groups = {}
    mechanism_sums = {}

    for post in posts:
        raw = post.get("mechanisms", [])

        if isinstance(raw, dict):
            active = {
                name for name in allowed
                if raw.get(name)
            }
        elif isinstance(raw, (list, tuple, set)):
            active = {
                name for name in raw
                if name in allowed
            }
        else:
            active = set()

        if not active:
            continue

        potential = float(
            post.get("potential", 0.0)
        )
        virality = float(
            post.get("virality", 0.0)
        )
        approval = float(
            post.get("approval", 0.0)
        )
        adjusted = float(
            post.get(
                "confidence_adjusted_potential",
                potential,
            )
        )

        for mechanism in active:
            agg = mechanism_sums.setdefault(
                mechanism,
                [0, 0.0],
            )
            agg[0] += 1
            agg[1] += potential

        if len(active) < 2:
            continue

        for size in (2, 3):
            for combo in itertools.combinations(
                sorted(active),
                size,
            ):
                agg = groups.setdefault(
                    combo,
                    [0, 0.0, 0.0, 0.0, 0.0],
                )
                agg[0] += 1
                agg[1] += potential
                agg[2] += virality
                agg[3] += approval
                agg[4] += adjusted

    mechanism_baseline = {
        mechanism: total / count
        for mechanism, (count, total)
        in mechanism_sums.items()
        if count
    }

    result = []

    for combo, agg in groups.items():
        count = agg[0]
        if count < min_posts:
            continue

        expected_parts = [
            mechanism_baseline[name]
            for name in combo
            if name in mechanism_baseline
        ]
        expected = (
            sum(expected_parts) / len(expected_parts)
            if expected_parts
            else 0.0
        )

        avg_potential = agg[1] / count

        result.append({
            "combination": list(combo),
            "posts_count": count,
            "avg_virality": round(
                agg[2] / count,
                2,
            ),
            "avg_approval": round(
                agg[3] / count,
                2,
            ),
            "avg_potential": round(
                avg_potential,
                2,
            ),
            "avg_confidence_adjusted_potential": round(
                agg[4] / count,
                2,
            ),
            "expected_potential_from_parts": round(
                expected,
                2,
            ),
            "lift": round(
                avg_potential - expected,
                2,
            ),
        })

    result.sort(
        key=lambda row: (
            row["lift"],
            row["avg_confidence_adjusted_potential"],
            row["posts_count"],
        ),
        reverse=True,
    )
    return result[:top_n]
def stable_mechanism_combinations(posts, mechanisms, min_posts=50, top_n=100):
    """Отдельный ТОП устойчивых комбинаций с минимальной выборкой 50 постов."""
    rows = mechanism_combinations(posts, mechanisms, min_posts=min_posts, top_n=top_n)
    return [row for row in rows if row.get('posts_count', 0) >= min_posts]

def temporal_stability_analysis(posts, mechanisms, periods=4, top_n_per_period=20):
    """Проверяет, сохраняются ли сильные комбинации механизмов в разных периодах."""
    if not posts:
        return {
            "method": {
                "periods": periods,
                "top_n_per_period": top_n_per_period,
                "minimum_occurrences_for_stability": 2,
                "note": "Нет данных для временного анализа.",
            },
            "periods": [],
            "stable_combinations": [],
        }

    ordered = sorted(posts, key=lambda p: p.get("timestamp", 0))
    total = len(ordered)
    chunks = []

    for i in range(periods):
        start_i = total * i // periods
        end_i = total * (i + 1) // periods
        chunk = ordered[start_i:end_i]
        if chunk:
            chunks.append(chunk)

    period_results = []
    history = {}

    for period_no, chunk in enumerate(chunks, 1):
        rows = mechanism_combinations(
            chunk,
            mechanisms,
            min_posts=20,
            top_n=top_n_per_period,
        )

        for rank, row in enumerate(rows, 1):
            combo = tuple(row.get("combination", []))
            if not combo:
                continue

            history.setdefault(combo, []).append({
                "period": period_no,
                "rank": rank,
                "posts_count": row.get("posts_count", 0),
                "lift": row.get("lift", 0),
                "avg_virality": row.get("avg_virality", 0),
                "avg_approval": row.get("avg_approval", 0),
                "avg_potential": row.get("avg_potential", 0),
                "avg_confidence_adjusted_potential": row.get(
                    "avg_confidence_adjusted_potential", 0
                ),
            })

        period_results.append({
            "period": period_no,
            "posts_count": len(chunk),
            "start_date": chunk[0].get("date"),
            "end_date": chunk[-1].get("date"),
            "top_combinations": rows,
        })

    stable = []
    period_count = len(chunks)

    for combo, occurrences in history.items():
        if len(occurrences) < 2:
            continue

        def avg(key):
            values = [float(x.get(key, 0)) for x in occurrences]
            return round(sum(values) / len(values), 2)

        stable.append({
            "combination": list(combo),
            "periods_present": len(occurrences),
            "stability_share": round(
                len(occurrences) / period_count, 3
            ),
            "avg_rank": avg("rank"),
            "avg_posts_count": avg("posts_count"),
            "avg_lift": avg("lift"),
            "avg_virality": avg("avg_virality"),
            "avg_approval": avg("avg_approval"),
            "avg_potential": avg("avg_potential"),
            "avg_confidence_adjusted_potential": avg(
                "avg_confidence_adjusted_potential"
            ),
            "periods": occurrences,
        })

    stable.sort(
        key=lambda x: (
            x["stability_share"],
            x["avg_lift"],
            x["avg_confidence_adjusted_potential"],
        ),
        reverse=True,
    )

    return {
        "method": {
            "periods": period_count,
            "top_n_per_period": top_n_per_period,
            "minimum_occurrences_for_stability": 2,
            "note": (
                "Устойчивость показывает повторяемость комбинации "
                "в разных временных периодах и не доказывает причинность."
            ),
        },
        "periods": period_results,
        "stable_combinations": stable,
    }



def temporal_oos_combination_validation(
    posts: list[dict],
    mechanisms: list[str],
    periods: int = 4,
    top_n_train: int = 30,
    min_train_posts: int = 8,
    min_test_posts: int = 3,
    min_periods_present: int = 2,
) -> dict:
    """
    Chronological out-of-sample validation for mechanism combinations.

    Проверяем пары и тройки отдельно: TOP-N для троек не должен
    вытеснять пары. Комбинация считается рабочей только если она
    переносится на следующие временные периоды, а не просто хорошо
    выглядит на обучающей истории.
    """
    if not posts or periods < 2:
        return {
            "method": "chronological_out_of_sample",
            "status": "insufficient_data",
            "splits": [],
            "stable_combinations": [],
        }

    ordered = sorted(posts, key=lambda p: float(p.get("timestamp", 0) or 0))
    n = len(ordered)
    chunk_size = max(1, n // periods)
    chunks = [
        ordered[i * chunk_size: (i + 1) * chunk_size if i < periods - 1 else n]
        for i in range(periods)
    ]
    chunks = [chunk for chunk in chunks if chunk]

    split_results = []
    combo_stats = {}

    for test_idx in range(1, len(chunks)):
        train_posts = [p for chunk in chunks[:test_idx] for p in chunk]
        test_posts = chunks[test_idx]

        if len(train_posts) < min_train_posts or len(test_posts) < min_test_posts:
            continue

        # Проверяем пары и тройки независимо, затем объединяем кандидатов.
        train_combinations = mechanism_combinations(
            train_posts,
            mechanisms,
            min_posts=min_train_posts,
            top_n=max(100, top_n_train * 10),
        )
        # Один расчёт возвращает пары и тройки; разделяем их только здесь.
        pair_candidates = [
            x for x in train_combinations
            if len(x.get("combination", [])) == 2
        ]
        triple_candidates = [
            x for x in train_combinations
            if len(x.get("combination", [])) == 3
        ]
        candidates = {
            "+".join(item["combination"]): item
            for item in (pair_candidates[:top_n_train] + triple_candidates[:top_n_train])
        }

        all_test_potential = sum(
            float(p.get("potential", 0.0) or 0.0) for p in test_posts
        ) / len(test_posts)

        evaluated = []
        for combo_key, train_item in candidates.items():
            combo = combo_key.split("+")
            matched_test = [
                p for p in test_posts
                if _combination_matches(
                    p.get("mechanisms", p.get("mechanism_list", [])), combo
                )
            ]
            test_count = len(matched_test)
            if test_count < min_test_posts:
                continue

            test_potential = sum(
                float(p.get("potential", 0.0) or 0.0) for p in matched_test
            ) / test_count
            test_virality = sum(
                float(p.get("virality", 0.0) or 0.0) for p in matched_test
            ) / test_count
            test_approval = sum(
                float(p.get("approval", 0.0) or 0.0) for p in matched_test
            ) / test_count
            lift = test_potential - all_test_potential

            evaluated.append({
                "combination": combo_key,
                "size": len(combo),
                "train_posts": int(train_item.get("posts_count", train_item.get("posts", 0)) or 0),
                "train_lift": float(train_item.get("lift", 0.0) or 0.0),
                "test_period": test_idx + 1,
                "test_posts": test_count,
                "test_potential": round(test_potential, 2),
                "test_virality": round(test_virality, 2),
                "test_approval": round(test_approval, 2),
                "test_lift": round(lift, 2),
                "transferred": bool(lift > 0),
            })

            stats = combo_stats.setdefault(combo_key, {
                "combination": combo_key,
                "size": len(combo),
                "test_periods": 0,
                "transferred_periods": 0,
                "test_posts_total": 0,
                "test_lift_sum": 0.0,
                "test_potential_sum": 0.0,
            })
            stats["test_periods"] += 1
            stats["transferred_periods"] += int(lift > 0)
            stats["test_posts_total"] += test_count
            stats["test_lift_sum"] += lift
            stats["test_potential_sum"] += test_potential

        evaluated.sort(key=lambda x: (x["test_lift"], x["test_posts"]), reverse=True)
        split_results.append({
            "train_through_period": test_idx,
            "test_period": test_idx + 1,
            "train_posts": len(train_posts),
            "test_posts_total": len(test_posts),
            "test_baseline_potential": round(all_test_potential, 2),
            "candidate_count": len(candidates),
            "evaluated_combinations": evaluated,
        })

    stable = []
    for combo_key, stats in combo_stats.items():
        if stats["test_periods"] < min_periods_present:
            continue

        avg_test_lift = stats["test_lift_sum"] / stats["test_periods"]
        transfer_share = stats["transferred_periods"] / stats["test_periods"]
        # Для 3 тестовых переходов требуем положительный lift минимум в 2.
        required_positive = max(2, int(math.ceil(stats["test_periods"] * 0.67)))
        generalizes = bool(
            stats["transferred_periods"] >= required_positive
            and avg_test_lift > 0
        )

        stable.append({
            "combination": combo_key,
            "size": stats["size"],
            "test_periods": stats["test_periods"],
            "transferred_periods": stats["transferred_periods"],
            "transfer_share": round(transfer_share, 3),
            "test_posts_total": stats["test_posts_total"],
            "avg_test_lift": round(avg_test_lift, 2),
            "avg_test_potential": round(
                stats["test_potential_sum"] / stats["test_periods"], 2
            ),
            "required_positive_periods": required_positive,
            "generalizes": generalizes,
        })

    stable.sort(
        key=lambda x: (x["generalizes"], x["transfer_share"], x["avg_test_lift"], x["test_posts_total"]),
        reverse=True,
    )

    return {
        "method": "chronological_out_of_sample",
        "status": "ok" if split_results else "insufficient_splits",
        "periods": len(chunks),
        "splits": split_results,
        "stable_combinations": stable,
        "note": (
            "Пары и тройки проверяются отдельно. Переносимость требует "
            "положительного lift минимум в 67% доступных тестовых периодов "
            "и положительного среднего lift. Это диагностический OOS-тест, "
            "а не доказательство причинности."
        ),
    }


def build_editorial_model_v1(posts, mechanism_report_data, temporal_data):
    """
    Финальная редакторская модель v1.0.

    Превращает историческую статистику в компактные правила для
    предварительной оценки свежей публикации. Это эвристическая модель,
    а не обученный прогноз.
    """
    mechanism_rows = []
    for name, row in mechanism_report_data.items():
        n = int(row.get("posts", 0))
        if n <= 0:
            continue

        # Доверие растет с выборкой и насыщается около 300 публикаций.
        sample_conf = min(1.0, math.sqrt(n / 300.0))
        potential = float(row.get("avg_potential", 0.0))
        virality = float(row.get("avg_virality", 0.0))
        approval = float(row.get("avg_approval", 0.0))
        adjusted = float(
            row.get("avg_confidence_adjusted_potential", potential)
        )

        mechanism_rows.append({
            "mechanism": name,
            "posts": n,
            "sample_confidence": round(sample_conf, 3),
            "virality": round(virality, 2),
            "approval": round(approval, 2),
            "potential": round(potential, 2),
            "confidence_adjusted_potential": round(adjusted, 2),
        })

    mechanism_rows.sort(
        key=lambda x: (
            x["confidence_adjusted_potential"],
            x["potential"],
            x["posts"],
        ),
        reverse=True,
    )

    # Комбинации попадают в рабочую модель только из OOS-валидации.
    # Старый temporal_stability_analysis оставляем диагностикой, но не
    # используем как основание для fresh-score: он in-sample.
    stable_rows = []
    oos_mode = False
    if isinstance(temporal_data, dict):
        if temporal_data.get("method") == "chronological_out_of_sample":
            oos_mode = True
            stable_rows = temporal_data.get("stable_combinations", []) or []
        else:
            # Обратная совместимость: старую временную статистику можно
            # передать в функцию, но она не получает право выдавать бонусы.
            stable_rows = []

    combination_rules = []
    for row in stable_rows:
        periods = int(row.get("test_periods", 0) or 0)
        transfer_share = float(row.get("transfer_share", 0.0) or 0.0)
        posts_count = float(row.get("test_posts_total", 0) or 0)
        lift = float(row.get("avg_test_lift", 0.0) or 0.0)
        potential = float(row.get("avg_test_potential", 0.0) or 0.0)

        if periods < 2 or posts_count < 6 or transfer_share < 0.67 or lift <= 0:
            continue

        # Градуированный OOS-бонус: сильный lift получает больший вес,
        # но бонус ограничен +4 и не зависит только от факта прохождения фильтра.
        # Стабильность учитывается отдельно, чтобы 2/2 не выглядело как 3/3.
        lift_component = min(3.0, max(0.0, lift) * 0.16)
        stability_component = min(1.0, max(0.0, transfer_share - 0.5) * 2.0)
        volume_component = min(0.5, max(0.0, math.log1p(posts_count) - math.log1p(10.0)) * 0.12)

        bonus = min(
            4.0,
            max(0.0, lift_component + stability_component + volume_component)
        )

        if bonus <= 0:
            continue

        reliability = "strong" if (
            periods >= 3 and transfer_share >= 0.67
        ) else "promising"

        combination_rules.append({
            "combination": str(row.get("combination", "")).split("+"),
            "test_periods": periods,
            "transfer_share": round(transfer_share, 3),
            "test_posts_total": int(posts_count),
            "avg_test_lift": round(lift, 2),
            "avg_test_potential": round(potential, 2),
            "reliability": reliability,
            "editorial_bonus": round(bonus, 2),
            "validation": "chronological_out_of_sample",
        })

    combination_rules.sort(
        key=lambda x: (
            x["reliability"] == "strong",
            x["editorial_bonus"],
            x["transfer_share"],
            x["test_posts_total"],
        ),
        reverse=True,
    )

    # Финальные правила уровня редактора.
    # Это не новые статистические веса, а интерпретация результатов.
    rules = [
        {
            "id": "R1",
            "name": "Необычность + визуальный повод + медиа",
            "when": ["unusual", "visual_hook", "media"],
            "effect": "сильный кандидат на высокий общий потенциал",
            "strength": "strong",
        },
        {
            "id": "R2",
            "name": "Необычность + тревожность/шок + медиа",
            "when": {"any_of": ["unusual", "fear", "shock"], "all_of": ["media"]},
            "effect": "сильный кандидат прежде всего на распространение",
            "strength": "strong",
        },
        {
            "id": "R3",
            "name": "Необычность + позитивная эмоция + медиа",
            "when": ["unusual", "positive_emotion", "media"],
            "effect": "перспективный кандидат на баланс охвата и одобрения",
            "strength": "promising",
        },
        {
            "id": "R4",
            "name": "Юмор",
            "when": ["humor"],
            "effect": "повышать приоритет, особенно при наличии визуального материала",
            "strength": "promising",
        },
    ]

    # Базовые пороги для практического использования.
    thresholds = {
        "priority": 62,
        "take": 55,
        "reserve": 52,
        "skip_below": 52,
        "note": "Пороговая шкала свежего скоринга: 62/55/52.",
    }

    return {
        "version": "1.0",
        "status": "final_for_operational_use_oos_calibrated",
        "purpose": (
            "Предварительная оценка свежих публикаций по историческим "
            "закономерностям аудитории."
        ),
        "score_components": {
            "virality": {
                "weight": 0.60,
                "meaning": "вероятность сильного распространения",
            },
            "approval": {
                "weight": 0.40,
                "meaning": "вероятность положительной реакции",
            },
            "combination_bonus_max": 4.0,
        },
        "thresholds": thresholds,
        "mechanisms": mechanism_rows,
        "combination_rules": combination_rules[:20],
        "editorial_rules": rules,
        "interpretation": {
            "strong": "использовать как устойчивый сигнал при отборе",
            "promising": "использовать как дополнительный сигнал, не как гарантию",
            "caution": (
                "модель не доказывает причинность и не заменяет проверку "
                "фактов, актуальности и качества источника"
            ),
            "combination_validation": (
                "комбинационные бонусы разрешены только при подтверждении "
                "на последующих временных периодах (chronological OOS)"
            ),
        },
    }


def _editorial_rule_matches(mechanisms, rule):
    """Проверяет, выполняется ли редакторское правило для набора механизмов."""
    when = rule.get("when")
    if isinstance(when, list):
        return all(item in mechanisms for item in when)

    if isinstance(when, dict):
        any_of = when.get("any_of", [])
        all_of = when.get("all_of", [])
        any_ok = (not any_of) or any(item in mechanisms for item in any_of)
        all_ok = all(item in mechanisms for item in all_of)
        return any_ok and all_ok

    return False


def _combination_matches(mechanisms, combination):
    """Комбинация считается выполненной, если все её механизмы присутствуют."""
    return all(item in mechanisms for item in combination)



def _fresh_signal_intensity_bonus(post, classification):
    """
    v2.8: калиброванный корректор силы свежего события.

    В отличие от старой версии бонус не пытается напрямую оценить
    вирусность по отдельным страшным словам. Он оценивает силу
    редакционного сигнала: масштаб последствий, тяжесть, ребёнок,
    экологическая опасность, карантин и подтверждённость.

    Бонус остаётся ограниченным и используется вместе с исторической
    моделью, а не вместо неё.
    """
    title = (post.get("title") or "").lower()
    body = (post.get("text") or "").lower()
    text = " ".join(part for part in (title, body) if part)
    bonus = 0.0

    death_count = len(re.findall(
        r"\b(?:погиб\w*|умер\w*|смерт\w*)\b", text
    ))
    if death_count >= 3:
        bonus += 4.0
    elif death_count == 2:
        bonus += 3.0
    elif death_count == 1:
        bonus += 1.5

    if any(w in text for w in (
        "тяжелом состоянии", "тяжёлом состоянии",
        "тяжелые травм", "тяжёлые травм",
        "госпитализирован", "госпитализировали"
    )):
        bonus += 1.5
    elif any(w in text for w in (
        "пострадал", "пострадали", "получила травмы", "получил травмы"
    )):
        bonus += 0.75

    child = any(w in text for w in (
        "ребен", "ребён", "девоч", "мальчик", "детск"
    ))
    accident = any(w in text for w in (
        "дтп", "сбил", "сбила", "наезд", "пешеходн", "столкнов"
    ))
    if child and accident:
        bonus += 2.0

    if "ртут" in text and any(w in text for w in (
        "пдк", "загрязнен", "загрязн"
    )):
        bonus += 2.0
    elif "пдк" in text and any(w in text for w in (
        "вода", "воздух", "почв"
    )):
        bonus += 1.25

    quarantine = any(w in text for w in ("карантин", "карантинн"))
    disease = any(w in text for w in (
        "болезн", "заболев", "инфекц", "вирус"
    ))
    animal = any(w in text for w in (
        "собак", "животн", "лошад", "кошк", "кот", "щен"
    ))
    if quarantine and disease and animal:
        bonus += 1.5
    elif quarantine and animal:
        bonus += 0.75

    if post.get("verified"):
        bonus += 0.5

    return min(8.0, bonus)


def _fresh_event_strength(post: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
    """
    v2.9 — калиброванная сила свежего события.

    Цель:
    - сила инфоповода определяется прежде всего самим событием;
    - подтверждение влияет на доверие, но не заменяет силу события;
    - неподтверждённые тяжёлые сообщения заметно понижаются;
    - несколько погибших дают сильный, но не безграничный прирост;
    - ребёнок + ДТП/наезд, экологическая угроза и карантин получают
      самостоятельный вес.
    """
    title = str(post.get("title") or "")
    body = str(post.get("text") or post.get("description") or "")
    source_text = f"{title} {body}".lower()

    mechanisms = set(classification.get("mechanisms") or [])
    verified = bool(post.get("verified", False))

    strength = 10.0
    components: Dict[str, float] = {"base": 10.0}

    def add(name: str, value: float) -> None:
        nonlocal strength
        if value:
            strength += value
            components[name] = round(value, 2)

    # ---------- Тяжесть происшествия ----------
    death_patterns = (
        r"\bпогиб\w*",
        r"\bумер\w*",
        r"\bскончал\w*",
        r"\bсмерт\w*",
    )
    death_hits = sum(len(re.findall(p, source_text)) for p in death_patterns)

    # Для количества погибших используем уровни, а не линейное сложение.
    # Важнее качественно отделить массовую гибель от одиночного случая,
    # чем бесконечно наращивать score за каждое слово.
    if death_hits >= 3:
        add("deaths_3plus", 38.0)
    elif death_hits == 2:
        add("deaths_2", 30.0)
    elif death_hits == 1:
        add("death_1", 19.0)

    injury_patterns = (
        r"\bпострада\w*",
        r"\bтравм\w*",
        r"\bранен\w*",
        r"\bгоспитализ\w*",
        r"\bв больниц\w*",
        r"\bреанимац\w*",
    )
    injury_hits = sum(len(re.findall(p, source_text)) for p in injury_patterns)

    if injury_hits >= 2:
        add("multiple_injury_signals", 12.0)
    elif injury_hits == 1:
        add("injury_signal", 8.0)

    severe = bool(re.search(
        r"\bтяжел\w* состояни\w*|\bреанимац\w*|\bкритическ\w*|\bугроз\w* жизни",
        source_text,
    ))
    if severe:
        add("severe_condition", 5.0)

    # ---------- Ребёнок + ДТП ----------
    child = bool(re.search(
        r"\bребён\w*|\bребен\w*|\bдет\w*|\bшкольник\w*|\bшкольниц\w*|"
        r"\bмальчик\w*|\bдевочк\w*",
        source_text,
    ))
    accident = (
        "incident" in mechanisms
        or bool(re.search(
            r"\bдтп\b|\bавари\w*|\bнаезд\w*|\bсбил\w*|\bстолкнов\w*",
            source_text,
        ))
    )
    if child and accident:
        add("child_accident", 17.0)

    # ---------- Карантин / опасная болезнь ----------
    quarantine = bool(re.search(
        r"\bкарантин\w*|\bограничен\w*",
        source_text,
    ))
    disease = bool(re.search(
        r"\bболезн\w*|\bинфекц\w*|\bзаболев\w*|\bвирус\w*|"
        r"\bэпидеми\w*|\bвспыш\w*",
        source_text,
    ))
    animal = "animal" in mechanisms

    if quarantine and disease:
        add("quarantine_disease", 22.0)
        if animal:
            add("animal_quarantine", 4.0)

    # ---------- Экология ----------
    pollution = bool(re.search(
        r"\bртут\w*|\bпдк\b|\bзагрязн\w*|\bтоксич\w*|\bядовит\w*|\bотравлен\w*",
        source_text,
    ))
    environment = bool(re.search(
        r"\bиртыш\w*|\bрек\w*|\bвод\w*|\bвоздух\w*|\bпочв\w*",
        source_text,
    ))
    if pollution:
        add("pollution", 19.0)
        if environment:
            add("environmental_context", 6.0)

    # ---------- Пожар ----------
    fire = bool(re.search(
        r"\bпожар\w*|\bзагорел\w*|\bвозгорани\w*",
        source_text,
    ))
    if fire and injury_hits >= 2:
        add("fire_with_multiple_injuries", 16.0)
    elif fire and injury_hits == 1:
        add("fire_with_injury", 11.0)
    elif fire:
        add("fire", 6.0)

    # ---------- Официальное подтверждение ----------
    # Это отдельный слой надёжности, а не основной источник силы.
    if verified:
        add("verified", 5.0)
    else:
        if death_hits or injury_hits >= 2:
            add("unverified_severe_event", -15.0)
        elif pollution or (quarantine and disease):
            add("unverified_public_risk", -8.0)
        else:
            add("unverified", -2.0)

    # ---------- Ограничение ----------
    # Сильные события могут выйти в 70–90, но одно ключевое слово
    # не должно разгонять оценку до 100.
    strength = max(0.0, min(100.0, strength))

    return {
        "score": round(strength, 2),
        "event_strength": round(strength, 2),
        "components": components,
        "death_count": death_hits,
        "injury_hits": injury_hits,
        "child_accident": bool(child and accident),
        "verified": verified,
    }

FRESH_ROAD_RE = re.compile(
    r"\bдтп\b|\bавари\w*|\bнаезд\w*|\bсбил\w*|\bсбила\w*|"
    r"\bстолкнов\w*|\bпешеход\w*"
)

FRESH_POLLUTION_RE = re.compile(
    r"\bртут\w*|\bпдк\b|\bзагрязн\w*|\bтоксич\w*"
)

FRESH_QUARANTINE_RE = re.compile(
    r"\bкарантин\w*|\bкарантинн\w*|\bочаг\w*"
)

FRESH_DISEASE_RE = re.compile(
    r"\bболезн\w*|\bзаболев\w*|\bинфекц\w*|\bвирус\w*"
)

FRESH_CHILD_RE = re.compile(
    r"\bребён\w*|\bребен\w*|\bдевоч\w*|\bмальчик\w*|\bдетск\w*"
)

FRESH_DEATH_RE = re.compile(
    r"\b(?:погиб\w*|умер\w*|смерт\w*)\b"
)

FRESH_EXPLICIT_ANIMAL_SUBSTRINGS = (
    "медвед", "собак", "пёс", "пес", "кот", "кошк",
    "котят", "борз", "щен", "животн", "лошад", "птиц",
    "голуб", "мыш", "звер", "лис", "барханн",
)

_MODEL_MECHANISM_CACHE = {}


def _get_mechanism_rows(editorial_model):
    """Return a cached mechanism lookup for one in-memory model object."""
    key = id(editorial_model)
    cached = _MODEL_MECHANISM_CACHE.get(key)
    if cached is not None:
        return cached

    cached = {
        row["mechanism"]: row
        for row in editorial_model.get("mechanisms", [])
        if row.get("mechanism")
    }
    _MODEL_MECHANISM_CACHE[key] = cached
    return cached


def prepare_fresh_classification(post, classification=None):
    """Normalize one fresh-news classification once for all audience models."""
    if classification is None:
        classification = classify_one(post)
    else:
        classification = dict(classification)
        if isinstance(
            classification.get("mechanism_strength"),
            dict,
        ):
            classification["mechanism_strength"] = dict(
                classification["mechanism_strength"]
            )

    text_lower = " ".join(
        part
        for part in (
            (post.get("title") or "").lower(),
            (post.get("text") or "").lower(),
        )
        if part
    )

    mechanisms = set(
        classification.get("mechanisms", [])
    )
    strengths = classification.setdefault(
        "mechanism_strength",
        {},
    )

    # Keep animal detection precise for incident texts.
    if (
        "animal" in mechanisms
        and FRESH_ROAD_RE.search(text_lower)
        and not any(
            pattern.search(text_lower)
            for pattern in ANIMAL_PATTERNS
        )
    ):
        mechanisms.discard("animal")
        strengths.pop("animal", None)

    # Targeted semantic boosts used by the fresh-event layer.
    if FRESH_POLLUTION_RE.search(text_lower):
        mechanisms.update(("shock", "fear"))
        strengths["shock"] = max(
            float(strengths.get("shock", 0.0)),
            0.65,
        )
        strengths["fear"] = max(
            float(strengths.get("fear", 0.0)),
            0.55,
        )

    if (
        FRESH_QUARANTINE_RE.search(text_lower)
        and FRESH_DISEASE_RE.search(text_lower)
    ):
        mechanisms.update(("incident", "fear"))
        strengths["incident"] = max(
            float(strengths.get("incident", 0.0)),
            0.60,
        )
        strengths["fear"] = max(
            float(strengths.get("fear", 0.0)),
            0.65,
        )

    child_incident = (
        FRESH_CHILD_RE.search(text_lower)
        and FRESH_ROAD_RE.search(text_lower)
    )
    child_injury = (
        FRESH_CHILD_RE.search(text_lower)
        and re.search(
            r"\bтравм\w*",
            text_lower,
        )
    )
    if child_incident or child_injury:
        mechanisms.update(("human_story", "shock"))
        strengths["human_story"] = max(
            float(strengths.get("human_story", 0.0)),
            0.65,
        )
        strengths["shock"] = max(
            float(strengths.get("shock", 0.0)),
            0.65,
        )

    if len(FRESH_DEATH_RE.findall(text_lower)) >= 2:
        mechanisms.update(("human_story", "shock"))
        strengths["human_story"] = max(
            float(strengths.get("human_story", 0.0)),
            0.70,
        )
        strengths["shock"] = max(
            float(strengths.get("shock", 0.0)),
            0.80,
        )

    # Preserve the older broad explicit-animal guard for rare edge cases.
    if (
        "animal" in mechanisms
        and FRESH_ROAD_RE.search(text_lower)
        and not any(
            token in text_lower
            for token in FRESH_EXPLICIT_ANIMAL_SUBSTRINGS
        )
    ):
        mechanisms.discard("animal")
        strengths.pop("animal", None)

    classification["mechanisms"] = sorted(mechanisms)
    classification["mechanism_strength"] = {
        key: value
        for key, value in strengths.items()
        if key in mechanisms
    }

    return classification



def score_fresh_post(post, editorial_model, classification=None):
    """
    Score one fresh story against one audience model.

    Classification is injectable so a story shared across several audience
    models is parsed only once.
    """
    classification = prepare_fresh_classification(
        post,
        classification=classification,
    )
    mechanisms = set(
        classification.get("mechanisms", [])
    )

    mechanism_rows = _get_mechanism_rows(
        editorial_model
    )

    # --------------------------------------------------------
    # 1. БАЗОВАЯ ОЦЕНКА ПО МЕХАНИЗМАМ
    # --------------------------------------------------------

    baseline_v = 50.0
    baseline_a = 50.0

    weighted_v = 0.0
    weighted_a = 0.0
    total_weight = 0.0

    mechanism_reasons = []

    for mechanism in sorted(mechanisms):

        row = mechanism_rows.get(mechanism)

        if not row:
            continue

        sample_conf = float(
            row.get("sample_confidence", 0.0)
        )

        # Даже слабая выборка должна иметь небольшой вес,
        # но не должна полностью определять результат.
        weight = max(0.15, sample_conf)

        historical_v = float(
            row.get("virality", baseline_v)
        )

        historical_a = float(
            row.get("approval", baseline_a)
        )

        # Подтягиваем слабые выборки к нейтральной точке 50.
        adjusted_v = (
            baseline_v
            + (historical_v - baseline_v) * sample_conf
        )

        adjusted_a = (
            baseline_a
            + (historical_a - baseline_a) * sample_conf
        )

        weighted_v += adjusted_v * weight
        weighted_a += adjusted_a * weight
        total_weight += weight

        mechanism_reasons.append({
            "mechanism": mechanism,
            "sample_confidence": round(
                sample_conf, 3
            ),
            "virality": round(
                adjusted_v, 2
            ),
            "approval": round(
                adjusted_a, 2
            ),
        })

    if total_weight > 0:
        virality = weighted_v / total_weight
        approval = weighted_a / total_weight
    else:
        virality = baseline_v
        approval = baseline_a

    # --------------------------------------------------------
    # 2. ИНТЕГРАЛЬНЫЙ POTENTIAL
    # --------------------------------------------------------

    potential = (
        virality * 0.60
        + approval * 0.40
    )

    # v2.1: не даём усреднению механизмов сжимать все свежие новости
    # около 50. Учитываем интенсивность конкретного события.
    fresh_signal_bonus = _fresh_signal_intensity_bonus(
        post,
        classification,
    )
    potential_before_combinations = potential
    potential += fresh_signal_bonus

    # v2.8: историческая модель отвечает за общий профиль аудитории,
    # но не должна полностью стирать масштаб конкретного события.
    # Для сильных свежих сигналов добавляем ограниченное смешивание
    # с абсолютной оценкой события.
    event_strength_raw = _fresh_event_strength(post, classification)
    event_strength = (
        event_strength_raw.get("score", 0.0)
        if isinstance(event_strength_raw, dict)
        else float(event_strength_raw)
    )

    # v2.10: event_strength должен реально влиять на итоговую
    # редакторскую оценку. Ранее при strength=58 итог менялся всего
    # примерно на 1 балл, поэтому шкала свежести была почти декоративной.
    event_lift = max(0.0, (event_strength - 25.0) * 0.28)
    event_lift = min(12.0, event_lift)

    if not bool(post.get("verified", False)):
        severe_unverified = bool(
            event_strength_raw.get("death_count", 0)
            or event_strength_raw.get("injury_hits", 0) >= 2
        ) if isinstance(event_strength_raw, dict) else False

        if severe_unverified:
            event_lift *= 0.25
        else:
            event_lift *= 0.65

    potential += event_lift

    # --------------------------------------------------------
    # 3. ИСТОРИЧЕСКИЕ КОМБИНАЦИИ
    # --------------------------------------------------------

    matched_combinations = []
    combination_bonus = 0.0

    combination_rules = editorial_model.get(
        "combination_rules",
        []
    )

    for rule in combination_rules:

        combination = rule.get(
            "combination",
            []
        )

        if not combination:
            continue

        if not _combination_matches(
            mechanisms,
            combination
        ):
            continue

        bonus = float(
            rule.get(
                "editorial_bonus",
                0.0
            )
        )

        matched_combinations.append({
            "combination": combination,
            "bonus": round(bonus, 2),
            "reliability": rule.get(
                "reliability"
            ),
            "periods_present": rule.get(
                "periods_present"
            ),
            "stability_share": rule.get(
                "stability_share"
            ),
            "lift": rule.get(
                "avg_lift"
            ),
        })

        # Не складываем перекрывающиеся комбинации: одна новость
        # получает только самый сильный подтвержденный OOS-сигнал.
        combination_bonus = max(combination_bonus, bonus)

    # Близкие исторические комбинации — только диагностический сигнал.
    # Они НЕ влияют на score: частичное совпадение не доказывает, что
    # исторический паттерн действительно применим к свежей новости.
    near_combinations = []
    near_combination_bonus = 0.0

    if combination_rules and mechanisms:
        for rule in combination_rules:
            combination = rule.get("combination", [])
            if not combination:
                continue

            combo_set = set(combination)
            matched = combo_set.intersection(mechanisms)
            missing = combo_set - mechanisms

            # Показываем только достаточно близкие комбинации:
            # минимум 2 совпавших механизма и хотя бы один отсутствующий.
            if len(matched) < 2 or not missing:
                continue

            coverage = len(matched) / len(combo_set)
            near_combinations.append({
                "combination": combination,
                "matched_mechanisms": sorted(matched),
                "missing_mechanisms": sorted(missing),
                "coverage": round(coverage, 3),
                "bonus": 0.0,
                "reliability": rule.get("reliability"),
                "periods_present": rule.get("periods_present"),
                "stability_share": rule.get("stability_share"),
                "lift": rule.get("avg_lift"),
            })

    # Частичное совпадение не добавляем к итоговому score.
    # combination_bonus содержит только полные исторические совпадения.
    combination_bonus = min(4.0, combination_bonus)

    # v2.12: мягкие истории про животных не должны конкурировать
    # с подтвержденными инцидентами только за счет комбинационного бонуса.
    soft_animal_news = (
        "animal" in mechanisms
        and "incident" not in mechanisms
        and "shock" not in mechanisms
        and "fear" not in mechanisms
        and "human_story" not in mechanisms
        and "usefulness" not in mechanisms
    )
    if soft_animal_news:
        combination_bonus = min(1.5, combination_bonus)

    # v2.14: graduated event dominance. Исторический комбинационный
    # бонус не должен заметно переоценивать уже сильное свежее событие.
    # Это только свежий редакционный слой; OOS-модель комбинаций не меняется.
    #
    # 40-49: бонус максимум +2.0
    # 50-59: бонус максимум +1.0
    # 60+:    бонус максимум +0.5
    # Так, например, подтвержденное событие с 3 погибшими (58) не
    # проигрывает более слабой новости только из-за animal+locality.
    if event_strength >= 60.0:
        combination_bonus = min(0.5, combination_bonus)
    elif event_strength >= 50.0:
        combination_bonus = min(1.0, combination_bonus)
    elif event_strength >= 40.0:
        combination_bonus = min(2.0, combination_bonus)

    # --------------------------------------------------------
    # 4. РЕДАКТОРСКИЕ ПРАВИЛА
    # --------------------------------------------------------

    editorial_rules = editorial_model.get(
        "editorial_rules",
        []
    )

    matched_rules = []

    for rule in editorial_rules:

        if not _editorial_rule_matches(
            mechanisms,
            rule
        ):
            continue

        matched_rules.append({
            "rule": rule.get("id"),
            "effect": rule.get("effect"),
            "strength": rule.get("strength"),
        })

    # --------------------------------------------------------
    # 5. ФИНАЛЬНЫЙ SCORE
    # --------------------------------------------------------

    potential = min(
        100.0,
        max(
            0.0,
            potential + combination_bonus
        )
    )

    # v2.11: калибровка статусов свежих новостей.
    # Не берем старые thresholds из editorial_model: модель могла
    # содержать прежнюю шкалу 80/68/55 и тем самым игнорировать
    # новую калибровку fresh-news.
    priority_threshold = 62.0
    take_threshold = 55.0
    reserve_threshold = 52.0

    if potential >= priority_threshold:
        editorial_status = "ПРИОРИТЕТ"

    elif potential >= take_threshold:
        editorial_status = "ВЗЯТЬ"

    elif potential >= reserve_threshold:
        editorial_status = "РЕЗЕРВ"

    else:
        editorial_status = "ПРОПУСК"

    # --------------------------------------------------------
    # 6. ОБОСНОВАНИЕ
    # --------------------------------------------------------

    reasons = []

    for item in mechanism_reasons:
        reasons.append(
            "mechanism "
            f"{item['mechanism']}: "
            f"V={item['virality']:.2f}, "
            f"A={item['approval']:.2f}"
        )

    for item in matched_combinations:
        reasons.append(
            "combination "
            f"{'+'.join(item['combination'])}: "
            f"+{item['bonus']:.2f}"
        )

    if not matched_combinations:
        for item in near_combinations[:3]:
            reasons.append(
                "near_combination "
                f"{'+'.join(item['combination'])} "
                f"({item['coverage']:.0%}): "
                f"diagnostic_only; "
                f"missing={','.join(item['missing_mechanisms'])}"
            )

    for item in matched_rules:
        if item.get("rule"):
            reasons.append(
                f"editorial_rule {item['rule']}: "
                f"{item.get('strength', 'n/a')}"
            )

    reasons.append(
        f"fresh_signal_bonus: +{fresh_signal_bonus:.2f}"
    )
    reasons.append(
        f"fresh_event_strength: {event_strength:.2f}/100"
    )
    reasons.append(
        f"event_strength_lift: +{event_lift:.2f}"
    )
    reasons.append(
        f"potential_before_combinations: "
        f"{potential_before_combinations:.2f}/100"
    )
    reasons.append(
        f"potential: {potential:.2f}/100"
    )

    # --------------------------------------------------------
    # 7. РИСКИ
    # --------------------------------------------------------

    risks = []

    if classification.get(
        "classification_confidence",
        0
    ) < 0.65:
        risks.append(
            "низкая уверенность классификации"
        )

    if not mechanisms:
        risks.append(
            "не определены механизмы"
        )

    if any(
        item.get("sample_confidence", 0) < 0.5
        for item in mechanism_reasons
    ):
        risks.append(
            "часть сигналов основана "
            "на небольшой исторической выборке"
        )

    return {
        "version": editorial_model.get(
            "version",
            "1.0"
        ),

        "virality_score": round(
            max(
                0.0,
                min(100.0, virality)
            ),
            2
        ),

        "approval_score": round(
            max(
                0.0,
                min(100.0, approval)
            ),
            2
        ),

        "potential_score": round(
            potential,
            2
        ),

        "potential_before_combinations": round(
            potential_before_combinations,
            2
        ),

        "fresh_signal_bonus": round(
            fresh_signal_bonus,
            2
        ),

        "fresh_event_strength": round(
            event_strength,
            2
        ),

        "editorial_status": editorial_status,

        "classification": classification,

        "mechanisms_used": sorted(
            mechanisms
        ),

        "mechanism_details": mechanism_reasons,

        "matched_combinations":
            matched_combinations,

        "near_combinations": near_combinations,

        "near_combination_bonus": round(
            near_combination_bonus,
            2
        ),

        "combination_bonus": round(
            combination_bonus,
            2
        ),

        "matched_editorial_rules":
            matched_rules,

        "reasons": reasons,

        "risks": risks,
    }

def editorial_backtest(posts, editorial_model, top_n=20):
    """Retrospective diagnostic using the same fresh-scoring path."""
    rows = []

    for post in posts:
        classification = prepare_fresh_classification(post)
        scored = score_fresh_post(
            post,
            editorial_model,
            classification=classification,
        )

        rows.append({
            "post_id": post.get("post_id"),
            "date": post.get("date"),
            "text": post.get("text", ""),
            "historical_potential": round(
                float(post.get("potential", 0)),
                2,
            ),
            "editorial_potential": scored["potential_score"],
            "editorial_status": scored["editorial_status"],
            "editorial_virality": scored["virality_score"],
            "editorial_approval": scored["approval_score"],
            "mechanisms": scored["mechanisms_used"],
            "matched_combinations": scored["matched_combinations"],
        })

    rows.sort(
        key=lambda row: row["editorial_potential"],
        reverse=True,
    )
    return rows[:top_n]
def make_report(group, posts):

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "dataset": {
            "group": group,
            "posts_analyzed": len(posts),
            "group_url": GROUP_URL,
        },
        "methodology": {
            "virality": {
                "meaning": "сила распространения поста",
                "weights": {
                    "repost_rate_percentile": 0.60,
                    "engagement_percentile": 0.25,
                    "views_velocity_percentile": 0.15,
                },
            },
            "approval": {
                "meaning": "сила положительной реакции аудитории",
                "weights": {
                    "like_rate_percentile": 0.75,
                    "engagement_percentile": 0.25,
                },
                "note": (
                    "Комментарии не считаются одобрением автоматически."
                ),
            },
            "potential": {
                "meaning": (
                    "рабочий интегральный показатель по VIRALITY и APPROVAL"
                ),
                "weights": {
                    "virality": 0.60,
                    "approval": 0.40,
                },
                "note": (
                    "Это observed potential, а не обученный прогноз."
                ),
            },
        },
        "content_types": content_type_report(posts),
        "mechanisms": mechanism_report(posts),
        "top_virality": [
            compact_post(p)
            for p in sorted(
                posts, key=lambda p: p["virality"], reverse=True
            )[:30]
        ],
        "top_approval": [
            compact_post(p)
            for p in sorted(
                posts, key=lambda p: p["approval"], reverse=True
            )[:30]
        ],
        "top_potential": [
            compact_post(p)
            for p in sorted(
                posts, key=lambda p: p["potential"], reverse=True
            )[:30]
        ],
    }
    mechanism_names = [
        "locality", "incident", "conflict", "human_story", "animal",
        "weather", "unusual", "humor", "shock", "fear",
        "positive_emotion", "usefulness", "help_request",
        "visual_hook", "question_cta", "emoji_hook", "media",
    ]

    report["mechanism_combinations"] = mechanism_combinations(
        posts,
        mechanism_names,
        min_posts=20,
        top_n=100,
    )
    report["stable_mechanism_combinations"] = stable_mechanism_combinations(
        posts, mechanism_names, min_posts=50, top_n=100
    )

    report["temporal_stability"] = temporal_stability_analysis(
        posts,
        mechanism_names,
        periods=4,
        top_n_per_period=20,
    )

    report["editorial_model_v1"] = build_editorial_model_v1(
        posts,
        report["mechanisms"],
        report["temporal_stability"],
    )
    report["editorial_backtest"] = editorial_backtest(
        posts,
        report["editorial_model_v1"],
        top_n=20,
    )

    return report


# ============================================================
# SAVE
# ============================================================
