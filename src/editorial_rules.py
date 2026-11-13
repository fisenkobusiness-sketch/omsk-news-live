"""Shared editorial hard filters and legacy-data cleanup.

This module intentionally contains only deterministic rules shared by both
pipeline stages. Ranking and source attribution remain in their own modules.
"""
from __future__ import annotations

import re
from typing import Any

EXCLUDED_TOPIC_PATTERNS = (
    "бпла", "беспилот", "дрон", "дроны", "дрона", "дронами",
    "воздушн", "тревог", "ракетн", "опасност", "пво",
)

PROMO_PHRASES = (
    "подписывайтесь", "подпишитесь", "подписывайся",
    "наши каналы", "самые свежие новости",
    "где публикуются самые свежие", "публикуем в нашем канале",
    "актуальную информацию", "в режиме онлайн",
    "следим за обстановкой", "ищите по запросу",
    "вся оперативная информация", "на правах рекламы",
    "партнёрский материал", "партнерский материал",
    "спецпроект компании", "брендированный материал",
    "благодаря поддержке предприятия", "благодаря поддержке компании",
    "при поддержке предприятия", "при поддержке компании",
    "программа «родные города»", 'программа "родные города"',
    "копирование тарифа", "перейдите со своим номером",
    "перейти от любого оператора", "сохранить номер и привычные условия",
    "предложение от мегафона",
)

PROMO_REGEXES = (
    r"\b(?:реклама|рекламный материал|партнёрский материал|партнерский материал)\b",
    r"\b(?:скидк\w*|промокод\w*|купить|покупайте|закажите|оформите заказ)\b",
    r"\b(?:благодаря|при) поддержк\w+ (?:омск\w* нпз|предприяти\w*|компани\w*|бренд\w*)",
    r"\bпрограмма\s+[«\"]?родные города[»\"]?",
    r"\b(?:новом видеопроекте|смотрите видео о переменах)\b",
    r"\b(?:бесплатно )?перейдите? со своим номером\b",
    r"\bперейти от любого оператора\b",
    r"\b(?:опция|предложение)\s+[«\"]?копирован\w*\s+тариф\w*",
)

LEGACY_FIELDS = frozenset({
    "verification_required",
    "publish_disclaimer_required",
    "disclaimer_required",
    "verification_note",
    "verification_status",
})


def topic_text(value: Any) -> str:
    """Collect editorially relevant text from a post or clustered topic."""
    if not isinstance(value, dict):
        return str(value or "").lower()
    parts = [value.get(key) for key in ("text", "title", "headline", "summary", "description")]
    members = value.get("members", [])
    if isinstance(members, list):
        for member in members:
            if isinstance(member, dict):
                parts.extend(member.get(key) for key in ("text", "title", "headline", "summary"))
                post = member.get("post")
                if isinstance(post, dict):
                    parts.extend(post.get(key) for key in ("text", "title", "headline", "summary"))
    return " ".join(str(part or "").lower() for part in parts)


def is_low_value_personal_conflict(value: Any) -> bool:
    """Filter isolated first-person quarrels with no broader public consequence."""
    text = topic_text(value)
    if not isinstance(value, dict):
        return False

    # A dispute repeated by multiple monitored sources may have become a broader story.
    sources = set()
    for member in value.get("members", []) or []:
        if not isinstance(member, dict):
            continue
        source = (
            member.get("source_name")
            or member.get("source")
            or member.get("url")
            or member.get("source_id")
        )
        if source:
            sources.add(str(source).strip().casefold())
    if len(sources) >= 2:
        return False

    first_person = re.search(
        r"\\b(?:я|мне|меня|со мной|мой|моя|моё|мои)\\b", text, re.IGNORECASE
    )
    interpersonal_dispute = re.search(
        r"(?:оскорб\\w*|поругал\\w*|ругал\\w*|накричал\\w*|"
        r"поссорил\\w*|конфликт\\w*|не уступил\\w* место|"
        r"сел\\w* на колен\\w*|села на колен\\w*)",
        text,
        re.IGNORECASE,
    )
    broader_consequence = re.search(
        r"(?:госпитализир\\w*|травм\\w*|полици\\w*|следствен\\w*|"
        r"уголовн\\w* дело|суд\\w*|прокуратур\\w*|"
        r"провер\\w* правоохранител\\w*|закрыл\\w* маршрут)",
        text,
        re.IGNORECASE,
    )
    return bool(first_person and interpersonal_dispute and not broader_consequence)


def is_excluded_topic(value: Any) -> bool:
    text = topic_text(value)
    return (
        any(pattern in text for pattern in EXCLUDED_TOPIC_PATTERNS)
        or is_low_value_personal_conflict(value)
    )


def is_promotional(value: Any) -> bool:
    text = topic_text(value)
    if any(phrase in text for phrase in PROMO_PHRASES):
        return True
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in PROMO_REGEXES)


def clean_legacy_metadata(value: Any) -> Any:
    """Remove obsolete verification gates inherited from old runtime JSON.

    The function is recursive because stale records may be nested in topic
    members. It preserves source facts, metrics, links and current editorial
    status fields.
    """
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key in LEGACY_FIELDS:
                continue
            if key == "publication_mode" and item == "verification_required":
                continue
            cleaned[key] = clean_legacy_metadata(item)
        return cleaned
    if isinstance(value, list):
        return [clean_legacy_metadata(item) for item in value]
    return value
