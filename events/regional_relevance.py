# -*- coding: utf-8 -*-
"""Диагностическая оценка региональной релевантности SourcePost."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable


# Сильные маркеры в содержании новости, а не в имени издателя.
_CONFIRMED_MARKERS = (
    "омск", "омича", "омич", "омичей", "омичи",
    "омская область", "омской области", "омском районе",
    "омский район", "омских", "омскому",
    "омгту", "омгу", "омский государственный",
    "омсктрансмаш", "авангард", "омские крылья",
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
    "авангард", "омские крылья",
)

# Сильные нерегиональные маркеры, опасные для широкого поиска.
_REJECT_MARKERS = (
    "калужско-рижск", "медведково", "мытищи",
    "новосибирск", "новосибирской", "новосибирском", "толмачёво", "нск",
    "челябинск", "челябинской", "тюмень", "тюменской",
    "забайкаль", "коми", "петербург", "санкт-петербург",
    "краснодар", "краснодарский", "москва", "московской",
    "поморье", "архангельск", "архангельской области",
    "северодвинск", "мурманск", "карелия", "карелии",
    "петрозаводск",
    "по регионам россии", "регионам россии", "в регионах россии",
    "по регионам страны", "по всей россии", "в разных регионах страны",
)

_NON_NEWS_MARKERS = (
    "авито", "авто.ру", "auto.ru",
    "ставка тв", "прогноз (кэф", "коэффициент",
)

# Google News иногда дописывает бренд издания к заголовку. Такой суффикс —
# метка источника, а не доказательство того, что сама новость про Омск.
_BRANDING_SUFFIX_RE = re.compile(
    r"\s*(?:[-–—|]\s*)?(?:"
    r"ngs55(?:\.ru)?|om1(?:\.ru)?|omskinform(?:\.ru)?|"
    r"омск-информ|супер\s*омск|суперомск|kvnews(?:\.ru)?|"
    r"коммерческие\s+вести|bk55(?:\.ru)?|"
    r"12\s*канал|город55(?:\.ru)?"
    r")\s*$",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")


def _norm(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "").lower()).strip()


def _strip_branding_suffix(value: Any) -> str:
    return _BRANDING_SUFFIX_RE.sub("", str(value or "")).strip()


def _contains_any(text: str, markers: Iterable[str]) -> list[str]:
    return [marker for marker in markers if marker in text]


def assess_regional_relevance(post: Dict[str, Any]) -> Dict[str, Any]:
    """Возвращает объяснимую оценку; ничего не отбрасывает сама."""
    source = post.get("source") or {}
    body = post.get("post") or {}
    meta = post.get("meta") or {}

    # Регион определяем по содержанию заголовка/описания.
    # Имя паблика, сайта или поискового запроса не должно само по себе
    # превращать материал о другом регионе в омскую новость.
    title = _norm(_strip_branding_suffix(body.get("text")))
    description = _norm(_strip_branding_suffix(meta.get("description")))
    publisher = _norm(meta.get("publisher") or source.get("source_name"))
    query_id = meta.get("query_id")
    content_text = " ".join(part for part in (title, description) if part)

    confirmed = _contains_any(content_text, _CONFIRMED_MARKERS)
    local_entities = _contains_any(content_text, _LOCAL_ENTITY_MARKERS)
    rejected = _contains_any(content_text, _REJECT_MARKERS)
    non_news = _contains_any(content_text, _NON_NEWS_MARKERS)

    # Издатель и запрос используются лишь как слабые вспомогательные сигналы.
    regional_publisher = any(
        marker in publisher
        for marker in (
            "омск", "gorod55", "kvnews", "superomsk",
            "ngs55", "трамплин", "иртыш", "суперомск", "bk55",
        )
    )

    if rejected and not confirmed and not local_entities:
        status = "REGION_REJECTED"
        score = 0
        reasons = [f"foreign_marker:{item}" for item in rejected]
    elif non_news and not confirmed and not local_entities:
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

        if confirmed or local_entities:
            score = 70 + (20 if regional_publisher else 0) + (10 if regional_query else 0)
            if local_entities and not confirmed:
                reasons.append("local_entity")
            status = "REGION_CONFIRMED"
        elif regional_publisher and regional_query:
            # Это только предположение: локальное издание и локальный запрос
            # ещё не доказывают региональность конкретной статьи.
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