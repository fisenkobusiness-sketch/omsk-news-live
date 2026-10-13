# -*- coding: utf-8 -*-
"""Editorial event-type classification, separate from clustering identity rules.

The clustering matcher intentionally retains its legacy type signal. This
module assigns a user-facing category after clustering, from the headline and
a short lead, so words buried in an article body cannot dominate the category.
"""
from __future__ import annotations

import re


_WORD_RE = re.compile(r"[0-9a-zа-яё]+", re.I)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _normalise(value: str) -> str:
    return str(value or "").lower().replace("ё", "е")


def _tokens(value: str) -> list[str]:
    return _WORD_RE.findall(_normalise(value))


def _has(tokens: list[str], stems: tuple[str, ...] | list[str]) -> bool:
    """Match prefixes at the start of words, never arbitrary substrings."""
    return any(token.startswith(stem) for token in tokens for stem in stems)


def _headline_and_context(value: str) -> tuple[str, str]:
    raw = str(value or "").replace("\r", "").strip()
    lines = [line.strip() for line in raw.split("\n") if line.strip()]
    if not lines:
        return "", ""
    headline = lines[0]
    if len(lines) > 1:
        first_lead = _SENTENCE_RE.split(lines[1], maxsplit=1)[0]
        context = f"{headline} {first_lead[:240]}"
    else:
        # Search headlines are usually a single line. For compact social posts
        # without explicit paragraph breaks, a bounded opening keeps context
        # while preventing distant details from deciding the category.
        context = headline[:360]
    return headline, context


def _is_uav_topic(tokens: list[str]) -> bool:
    return _has(tokens, ("дрон", "бпла", "беспилот", "беспилотник"))


def _is_road_accident(headline: str) -> bool:
    tokens = _tokens(headline)
    uav_topic = _is_uav_topic(tokens)
    explicit_accident = _has(
        tokens,
        ("дтп", "авари", "столкнов", "наезд", "перевернул", "протаран"),
    )
    vehicle_or_person = _has(
        tokens,
        (
            "автомобил", "машин", "автобус", "водител", "пешеход",
            "иномарк", "honda", "большегруз", "грузовик", "мотоцикл",
            "велосипед", "пассажир", "ребен", "дет", "пожил", "пенсионер",
            "человек", "мужчин", "женщин",
        ),
    )
    collision_verb = _has(
        tokens,
        ("сбил", "сбила", "сбили", "сбило", "переехал", "переехали",
         "врезал", "врезалась", "влетел", "влетела", "протаранил"),
    )
    # Air-defence reports often say drones were "shot down"; that is not a
    # road accident unless the headline explicitly describes a road crash.
    if uav_topic and not explicit_accident:
        return False
    return explicit_accident or (collision_verb and vehicle_or_person)


def classify_editorial_event_type(value: str) -> str:
    """Return one of the existing event types without changing clustering.

    Categories are inferred from the headline and first lead sentence. The
    existing schema is preserved: accident, fire, weather, transport, social,
    crime, politics, or general.
    """
    headline, context = _headline_and_context(value)
    if not headline:
        return "general"

    head_tokens = _tokens(headline)
    context_tokens = _tokens(context)
    head = _normalise(headline)

    # A commemorative day about the fire service is not an active fire incident.
    if (
        _has(head_tokens, ("день",))
        and _has(head_tokens, ("пожарн",))
        and _has(head_tokens, ("охран",))
        and _has(context_tokens, ("отмеч", "праздник", "поздравляем"))
    ):
        return "general"

    if _is_road_accident(headline):
        return "accident"

    # Fire wins over figurative wording such as "flames higher than poles".
    if _has(head_tokens, ("пожар", "загорел", "горит", "горел", "возгор", "пламя", "огонь")):
        return "fire"

    # Weather forecasts and space-weather warnings were missing from the old
    # lexicon, despite being explicit in the headline.
    if _has(
        head_tokens,
        ("погода", "погод", "прогноз", "потепл", "похолод", "температур",
         "дожд", "снег", "метел", "гололед", "мороз", "ветер", "ветр",
         "магнитн", "циклон", "антициклон"),
    ):
        return "weather"

    # Social assistance, payroll, pensions, tariffs and household utilities.
    if _has(
        head_tokens,
        ("стипенд", "зарплат", "пенси", "выплат", "пособ", "льгот", "тариф",
         "осаг", "страхов", "отоплен", "горячая", "квартплат", "коммунал",
         "перерасчет", "перерасчёт", "надбавк"),
    ):
        return "social"

    # A traffic-police activity report is transport/safety reporting, not a
    # criminal case simply because details mention police or court vocabulary.
    if _has(head_tokens, ("госавтоинспек", "гибдд")):
        return "transport"

    # Token-prefix matching avoids false crime labels when "суд" only appears
    # inside words such as "государственный".
    if _has(
        head_tokens,
        ("приговор", "задерж", "уголов", "мошеннич", "обвиня", "арест",
         "краж", "воров", "убил", "избил", "терроризм", "осужден",
         "осудили", "лжегадал", "финансированием"),
    ):
        return "crime"

    # Budget revisions belong to regional policy/economics in this taxonomy;
    # roads mentioned later in the article must not turn them into transport.
    if _has(head_tokens, ("бюджет", "доходы", "расходы")) and _has(
        head_tokens,
        ("увелич", "предлож", "планир", "вырос", "рост", "доход", "расход"),
    ):
        return "politics"

    # Routes, trains and flights were frequently left as general because the
    # old keyword list only recognised a few surface forms.
    if _has(
        head_tokens,
        ("электрич", "поезд", "рейс", "аэропорт", "летать", "улет", "вылет",
         "авиакомпан", "автобус", "трамва", "троллейб", "маршрут",
         "перекрыт", "движени", "мост", "госавтоинспек", "гибдд"),
    ):
        return "transport"

    # A building project merely associated with a deputy is not automatically
    # political; reserve this category for official actions and appointments.
    if (
        _has(head_tokens, ("депутат",))
        and _has(head_tokens, ("многоэтаж", "дом", "застрой", "строитель"))
        and not _has(head_tokens, ("предлож", "заявил", "выступил", "закон", "голос", "назнач"))
    ):
        return "general"

    if _has(
        head_tokens,
        ("губернатор", "мэр", "чиновник", "правительств", "депутат",
         "назнач", "отстав", "парламент", "министерств"),
    ):
        return "politics"

    # An attack/air-defence headline has no dedicated category in the current
    # schema. Keep it general rather than mislabelling it as a road accident or
    # politics because a governor is mentioned in a later paragraph.
    if _is_uav_topic(context_tokens):
        return "general"

    return "general"
