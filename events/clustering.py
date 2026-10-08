# -*- coding: utf-8 -*-
"""Conservative SourcePost -> NewsEvent clustering.

The first implementation is deterministic and intentionally diagnostic-only.
It does not modify scoring, datasets, or publication routing.
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Tuple


_WS_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+", re.I)
_NONWORD_RE = re.compile(r"[^0-9a-zа-яё]+", re.I)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")

EVENT_WINDOWS_MINUTES = {
    "accident": 180,
    "fire": 240,
    "weather": 360,
    "transport": 360,
    "social": 720,
    "crime": 360,
    "politics": 720,
    "general": 240,
}

EVENT_KEYWORDS = {
    "accident": ("дтп", "авар", "столкнов", "сбил", "наезд", "перевернул"),
    "fire": ("пожар", "загорел", "горит", "горел", "возгора"),
    "weather": ("снег", "дожд", "погода", "метел", "гололед", "мороз", "ветер"),
    "transport": ("маршрут", "автобус", "трамва", "троллейб", "дорог", "перекрыт", "движени"),
    "social": ("тариф", "выплат", "пособ", "льгот", "зарплат", "пенси"),
    "crime": ("суд", "приговор", "задерж", "уголов", "полици", "прокурат"),
    "politics": ("губернатор", "мэр", "чиновник", "правительств", "депутат", "назначен", "отстав"),
}


def _text(post: Dict[str, Any]) -> str:
    return str((post.get("post") or {}).get("text") or "").strip()


def normalize_text(value: str) -> str:
    value = _URL_RE.sub(" ", value.lower())
    value = value.replace("ё", "е")
    value = _NONWORD_RE.sub(" ", value)
    return _WS_RE.sub(" ", value).strip()


def token_set(value: str) -> set[str]:
    return {x for x in normalize_text(value).split() if len(x) >= 3}


def extract_numbers(value: str) -> set[str]:
    return set(_NUMBER_RE.findall(value or ""))


def detect_event_type(value: str) -> str:
    text = normalize_text(value)
    scores = {
        kind: sum(1 for keyword in keywords if keyword in text)
        for kind, keywords in EVENT_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else "general"


def extract_entities(value: str) -> Dict[str, List[str]]:
    # Lightweight entities for the first deterministic pass.
    # Proper NER is intentionally deferred until real clustering diagnostics exist.
    text = normalize_text(value)
    tokens = token_set(value)
    places = sorted(
        token for token in tokens
        if token in {
            "омск", "омская", "область", "город", "центр",
            "ленинский", "октябрьский", "советский", "кировский",
            "кормиловка", "тарский", "исилькуль", "марьяновка",
        }
    )
    return {
        "places": places,
        "numbers": sorted(extract_numbers(value)),
        "event_type": [detect_event_type(text)],
    }


def _published_minutes(post: Dict[str, Any]) -> float | None:
    value = (post.get("post") or {}).get("published_at")
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() / 60
    except ValueError:
        return None


def _source_key(post: Dict[str, Any]) -> str:
    source = post.get("source") or {}
    return f"{source.get('platform','')}:{source.get('source_id','')}"


def _post_url(post: Dict[str, Any]) -> str:
    return str((post.get("post") or {}).get("url") or "").strip()


def _same_time(a: Dict[str, Any], b: Dict[str, Any], window: int) -> bool:
    ta, tb = _published_minutes(a), _published_minutes(b)
    if ta is None or tb is None:
        return True
    return abs(ta - tb) <= window


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    sa, sb = token_set(a), token_set(b)
    jaccard = len(sa & sb) / len(sa | sb) if sa and sb else 0.0
    return max(seq, jaccard)


def _can_merge(post: Dict[str, Any], event: Dict[str, Any]) -> Tuple[bool, str, float]:
    text = _text(post)
    normalized = normalize_text(text)
    event_type = detect_event_type(text)
    window = EVENT_WINDOWS_MINUTES.get(event_type, EVENT_WINDOWS_MINUTES["general"])

    if _post_url(post) and _post_url(post) == event.get("canonical_url"):
        return True, "exact_url", 1.0

    if normalized and normalized == event.get("normalized_text"):
        return True, "normalized_text", 1.0

    if not _same_time(post, event["representative_post"], window):
        return False, "time_window", 0.0

    event_type_match = event_type == event.get("event_type")
    similarity = _similarity(normalized, event.get("normalized_text", ""))

    current_entities = extract_entities(text)
    event_entities = event.get("entities", {})
    number_match = bool(current_entities["numbers"]) and bool(
        set(current_entities["numbers"]) & set(event_entities.get("numbers", []))
    )
    place_match = bool(current_entities["places"]) and bool(
        set(current_entities["places"]) & set(event_entities.get("places", []))
    )

    if similarity >= 0.92 and event_type_match:
        return True, "high_text_similarity", similarity

    if similarity >= 0.84 and event_type_match and (place_match or number_match):
        return True, "text_similarity_plus_entity", similarity

    return False, "no_match", similarity


def _event_id(posts: List[Dict[str, Any]]) -> str:
    keys = sorted(
        f"{p.get('source',{}).get('platform','')}:{p.get('source',{}).get('source_id','')}:{p.get('post',{}).get('id','')}"
        for p in posts
    )
    digest = hashlib.sha1("|".join(keys).encode("utf-8")).hexdigest()[:16]
    return f"evt_{digest}"


def _build_event(posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(
        posts,
        key=lambda p: _published_minutes(p) if _published_minutes(p) is not None else float("inf"),
    )
    first = ordered[0]
    texts = [_text(p) for p in ordered]
    canonical = max(texts, key=len) if texts else ""

    first_ts = (first.get("post") or {}).get("published_at")
    last_ts = max(
        ((p.get("post") or {}).get("published_at") for p in ordered if (p.get("post") or {}).get("published_at")),
        default=first_ts,
    )

    source_keys = {_source_key(p) for p in posts}
    platforms = {(p.get("source") or {}).get("platform") for p in posts}
    urls = {_post_url(p) for p in posts if _post_url(p)}

    first_platform = (first.get("source") or {}).get("platform", "unknown")
    discovery_path = []
    for p in ordered:
        platform = (p.get("source") or {}).get("platform", "unknown")
        if platform not in discovery_path:
            discovery_path.append(platform)

    entities = extract_entities(canonical)

    return {
        "event_id": _event_id(posts),
        "first_seen_at": first_ts,
        "last_seen_at": last_ts,
        "first_source": first_platform,
        "source_count": len(posts),
        "independent_source_count": len(source_keys),
        "platform_count": len(platforms),
        "source_posts": posts,
        "canonical_text": canonical,
        "normalized_text": normalize_text(canonical),
        "representative_post": first,
        "entities": entities,
        "verification": {"state": "UNVERIFIED", "primary_sources": [], "secondary_sources": []},
        "discovery_path": discovery_path,
        "canonical_url": next(iter(urls), None),
        "event_type": entities["event_type"][0],
        "cluster_method": "deterministic_v1",
    }


def cluster_source_posts(source_posts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    ordered_posts = sorted(
        list(source_posts),
        key=lambda p: _published_minutes(p) if _published_minutes(p) is not None else float("inf"),
    )

    for post in ordered_posts:
        best = None
        best_reason = ""
        best_similarity = -1.0

        for index, event in enumerate(events):
            matched, reason, similarity = _can_merge(post, event)
            if matched and similarity > best_similarity:
                best = index
                best_reason = reason
                best_similarity = similarity

        if best is None:
            events.append(_build_event([post]))
            continue

        event = events[best]
        posts = list(event["source_posts"]) + [post]
        updated = _build_event(posts)
        updated["cluster_reason_last"] = best_reason
        updated["cluster_similarity_last"] = round(best_similarity, 4)
        events[best] = updated

    return events
