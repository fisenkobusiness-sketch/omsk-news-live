# -*- coding: utf-8 -*-
"""Диагностическая оценка региональной релевантности SourcePost."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Tuple


# Уникальные/сильные омские маркеры. Они не требуют буквального "Омск".
_CONFIRMED_MARKERS = (
    "омск", "омича", "омич", "омичей", "омичи",
    "омская область", "омской области", "омском районе",
    "омский район", "омских", "омскому",
    "омгту", "омгу", "омский государственный",
    "омсктрансмаш", "авангард", "омские крылья",
    "12 канал", "город55", "города55", "ngs55",
)

# Устойчивые сущности Омска/Омской области. Используются как сильный
# региональный сигнал даже без буквального упоминания "Омск".
_LOCAL_ENTITY_MARKERS = (
    "хоценко", "виталию хоценко", "виталием хоценко",
    "правительств омской области", "губернатор омской области",
    "мэр омска", "мэрии омска", "администрации омска",
    "омский аэропорт", "омский нпз", "омский нефтеперерабатывающий",
    "омский район", "омская область",
    "омгу", "омгту", "омский государственный университет",
    "омский государственный технический университет",
    "омский университет", "омсктрансмаш",
    "авангард", "омские крылья", "12 канал",
)

# Сильные нерегиональные маркеры, которые особенно опасны для широкого поиска.
_REJECT_MARKERS = (
    "калужско-рижск", "медведково", "мытищи",
    "новосибирск", "новосибирской", "новосибирском", "толмачёво", "нск",
    "челябинск", "челябинской", "тюмень", "тюменской",
    "забайкаль", "коми", "петербург", "санкт-петербург",
    "краснодар", "краснодарский", "москва", "московской",
)

_NON_NEWS_MARKERS = (
    "авито", "авто.ру", "auto.ru",
    "ставка тв", "прогноз (кэф", "коэффициент",
)

_WS_RE = re.compile(r"\s+")


def _norm(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "").lower()).strip()


def _contains_any(text: str, markers: Iterable[str]) -> list[str]:
    return [marker for marker in markers if marker in text]


def assess_regional_relevance(post: Dict[str, Any]) -> Dict[str, Any]:
    """Возвращает explainable-оценку; ничего не отбрасывает."""
    source = post.get("source") or {}
    body = post.get("post") or {}
    meta = post.get("meta") or {}

    title = _norm(body.get("text"))
    description = _norm(meta.get("description"))
    publisher = _norm(meta.get("publisher") or source.get("source_name"))
    query_id = meta.get("query_id")
    text = " ".join(part for part in (title, description, publisher) if part)

    confirmed = _contains_any(text, _CONFIRMED_MARKERS)
    local_entities = _contains_any(text, _LOCAL_ENTITY_MARKERS)
    rejected = _contains_any(text, _REJECT_MARKERS)
    non_news = _contains_any(text, _NON_NEWS_MARKERS)

    # Издатель — только вспомогательный сигнал. Сам по себе он не доказывает,
    # что материал про Омск: даже om1 публикует материалы других регионов.
    regional_publisher = any(
        marker in publisher
        for marker in (
            "омск", "gorod55", "kvnews", "superomsk",
            "ngs55", "трамплин", "иртыш", "суперомск", "bk55",
        )
    )

    if rejected and not confirmed:
        status = "REGION_REJECTED"
        score = 0
        reasons = [f"foreign_marker:{item}" for item in rejected]
    elif non_news and not confirmed:
        status = "REGION_REJECTED"
        score = 0
        reasons = [f"non_news_marker:{item}" for item in non_news]
    else:
        score = 0
        reasons = []
        if confirmed:
            score += 70
            reasons.append("regional_marker")
        regional_query = query_id in {
            "omsk_oblast", "omsk_incident", "omsk_dtp", "omsk_fire",
            "omsk_court", "omsk_transport", "omsk_social",
            "omsk_schools", "omsk_weather", "om1", "kvnews",
            "superomsk", "ngs55", "omskinform",
        }
        if regional_publisher:
            reasons.append("regional_publisher")
        if regional_query:
            reasons.append("regional_query")

        # Без явного омского маркера оставляем LIKELY только при двух
        # независимых слабых сигналах: локальный издатель + локальный запрос.
        if confirmed or local_entities:
            score = 70 + (20 if regional_publisher else 0) + (10 if regional_query else 0)
            reasons.append("local_entity") if local_entities and not confirmed else None
            status = "REGION_CONFIRMED"
        elif regional_publisher and regional_query:
            score = 30
            status = "REGION_LIKELY"
        else:
            status = "REGION_REJECTED"
            score = 0
            reasons.append("no_regional_signal")

    return {
        "regional_relevance": min(score, 100),
        "regional_status": status,
        "regional_reasons": reasons,
        "regional_markers": confirmed,
        "local_entities": local_entities,
        "foreign_markers": rejected,
        "non_news_markers": non_news,
    }
