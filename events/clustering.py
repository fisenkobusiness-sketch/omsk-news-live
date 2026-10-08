# -*- coding: utf-8 -*-
"""Conservative SourcePost -> NewsEvent clustering v5.

Diagnostic-only clustering. Scoring, datasets and publication routing are untouched.
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

# Cross-platform discovery is allowed a wider publication lag than same-type
# duplicate clustering. The source still has to be recent relative to the event.
CROSS_PLATFORM_WINDOW_MINUTES = 24 * 60

EVENT_KEYWORDS = {
    "accident": ("дтп", "авар", "столкнов", "сбил", "наезд", "перевернул"),
    "fire": ("пожар", "загорел", "горит", "горел", "возгора"),
    "weather": ("снег", "дожд", "погода", "метел", "гололед", "мороз", "ветер"),
    "transport": ("маршрут", "автобус", "трамва", "троллейб", "дорог", "перекрыт", "движени"),
    "social": ("тариф", "выплат", "пособ", "льгот", "зарплат", "пенси"),
    "crime": ("суд", "приговор", "задерж", "уголов", "полици", "прокурат"),
    "politics": ("губернатор", "мэр", "чиновник", "правительств", "депутат", "назначен", "отстав"),
}

# Generic Russian words carry almost no cross-platform identity signal.
_STOPWORDS = {
    "омск", "омске", "омска", "омский", "область", "области", "област", "город",
    "стали", "стал", "стала", "стало", "новый", "новая", "новое", "новые",
    "рассказал", "рассказали", "сообщили", "сообщает", "стало", "известно",
    "сегодня", "завтра", "вчера", "свежие", "данные", "жители", "люди",
    "местные", "регионе", "регион", "время", "день", "дни",
}


def _text(post: Dict[str, Any]) -> str:
    return str((post.get("post") or {}).get("text") or "").strip()


def _platform(post: Dict[str, Any]) -> str:
    return str((post.get("source") or {}).get("platform") or "")


def normalize_text(value: str) -> str:
    value = _URL_RE.sub(" ", value.lower())
    value = value.replace("ё", "е")
    value = _NONWORD_RE.sub(" ", value)
    return _WS_RE.sub(" ", value).strip()


def token_set(value: str) -> set[str]:
    return {x for x in normalize_text(value).split() if len(x) >= 3}


def meaningful_tokens(value: str) -> set[str]:
    return {x for x in token_set(value) if x not in _STOPWORDS}


def _token_fuzzy_match(left: set[str], right: set[str]) -> set[tuple[str, str]]:
    """Conservative fuzzy token matches for Russian inflectional variants."""
    matches: set[tuple[str, str]] = set()
    for a in left:
        if len(a) < 5:
            continue
        for b in right:
            if len(b) < 5:
                continue
            ratio = SequenceMatcher(None, a, b).ratio()
            if ratio >= 0.86:
                matches.add((a, b))
    return matches


def _semantic_overlap(left: set[str], right: set[str]) -> tuple[set[str], set[tuple[str, str]]]:
    exact = left & right
    fuzzy = _token_fuzzy_match(left - exact, right - exact)
    return exact, fuzzy


# Words that frequently co-occur in unrelated stories and therefore cannot
# serve as the sole morphology anchor.
_MORPHOLOGY_GENERIC = {
    "строительство", "строительства", "строить", "проект", "проекты",
    "домов", "дом", "жилых", "многоквартирных", "сообщили", "сообщает",
    "остаются", "осталось", "получил", "получила", "мужчина", "женщина",
    "авария", "аварии", "произошла", "произошел", "произошли",
    "после", "утром", "сегодня", "новая", "новый",
)


def _morphology_anchors(
    exact: set[str],
    fuzzy_overlap: set[tuple[str, str]],
) -> tuple[set[str], int]:
    exact_anchors = {
        token for token in exact
        if token not in _MORPHOLOGY_GENERIC and len(token) >= 6
    }
    fuzzy_anchors = {
        (a, b) for a, b in fuzzy_overlap
        if a not in _MORPHOLOGY_GENERIC and b not in _MORPHOLOGY_GENERIC
        and min(len(a), len(b)) >= 7
    }
    return exact_anchors, len(fuzzy_anchors)


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


def _publisher(post: Dict[str, Any]) -> str:
    return str((post.get("meta") or {}).get("publisher") or "").strip().lower()


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


def _match_text(post: Dict[str, Any]) -> str:
    """Text used for semantic matching; web search may have useful RSS description."""
    text = _text(post)
    if _platform(post) == "web_search":
        description = str((post.get("meta") or {}).get("description") or "").strip()
        if description and description not in text:
            text = f"{text} {description}"
    return text


def _event_match_text(event: Dict[str, Any]) -> str:
    texts = []
    for post in event.get("source_posts") or []:
        value = _match_text(post)
        if value:
            texts.append(value)
    canonical = str(event.get("canonical_text") or "").strip()
    if canonical and canonical not in texts:
        texts.append(canonical)
    return max(texts, key=len) if texts else canonical


def _cross_platform_match(post: Dict[str, Any], event: Dict[str, Any]) -> Tuple[bool, str, float]:
    """Match a short web-search headline to a longer social post conservatively."""
    other = event.get("representative_post") or {}
    if _platform(post) == _platform(other):
        return False, "same_platform", 0.0

    if not _same_time(post, other, CROSS_PLATFORM_WINDOW_MINUTES):
        return False, "cross_platform_time_window", 0.0

    left = meaningful_tokens(_match_text(post))
    right = meaningful_tokens(_event_match_text(event))

    if not left or not right:
        return False, "cross_platform_no_tokens", 0.0

    overlap, fuzzy_overlap = _semantic_overlap(left, right)
    matched_left = {a for a, _ in fuzzy_overlap} | overlap
    matched_right = {b for _, b in fuzzy_overlap} | overlap
    recall = len(matched_left) / len(left)
    precision = len(matched_right) / len(right)
    seq = SequenceMatcher(None, normalize_text(_match_text(post)), normalize_text(_event_match_text(event))).ratio()

    current_entities = extract_entities(_text(post))
    event_entities = event.get("entities", {})
    numbers = set(current_entities["numbers"]) & set(event_entities.get("numbers", []))
    places = set(current_entities["places"]) & set(event_entities.get("places", []))
    type_match = current_entities["event_type"][0] == event.get("event_type")

    # Strong anchor: numbers or concrete place tokens. For titles without them,
    # require at least two uncommon shared tokens and high title recall.
    uncommon_overlap = {t for t in matched_left if len(t) >= 5 and t not in _STOPWORDS}
    fuzzy_count = len(fuzzy_overlap)
    strong_anchor = bool(numbers or places or len(uncommon_overlap) >= 2)

    if recall >= 0.78 and strong_anchor:
        score = 0.60 * recall + 0.20 * min(1.0, len(uncommon_overlap) / 3) + 0.10 * int(type_match) + 0.10 * min(1.0, seq)
        return True, "title_in_body", score

    # Headlines and social posts often use different Russian inflections
    # (e.g. реликвий/реликвия, православных/православной). Accept a pair
    # when several distinctive words line up, but require the same event type
    # and at least one long lexical anchor to avoid generic-word collisions.
    exact_anchors, fuzzy_anchor_count = _morphology_anchors(overlap, fuzzy_overlap)
    long_fuzzy = sum(1 for a, b in fuzzy_overlap if min(len(a), len(b)) >= 8)

    # Morphology alone is not enough: common news vocabulary (construction,
    # houses, accident, man, after, etc.) must never form an event identity.
    # Require either two distinctive exact anchors or two distinctive
    # inflectional anchors, plus the same event type.
    morphology_anchor = len(exact_anchors) >= 2 or fuzzy_anchor_count >= 2
    if type_match and morphology_anchor and strong_anchor:
        score = 0.45 * recall + 0.20 * min(1.0, (len(exact_anchors) + fuzzy_anchor_count) / 3) + 0.20 * int(type_match) + 0.15 * seq
        return True, "morphology_match", score

    if recall >= 0.62 and type_match and strong_anchor and (numbers or places):
        score = 0.50 * recall + 0.20 * int(type_match) + 0.20 * min(1.0, len(numbers | places) / 2) + 0.10 * seq
        return True, "entity_match", score

    if seq >= 0.84 and type_match:
        return True, "cross_platform_similarity", seq

    return False, "cross_platform_no_match", max(recall, seq)


def _can_merge(post: Dict[str, Any], event: Dict[str, Any]) -> Tuple[bool, str, float]:
    text = _text(post)
    normalized = normalize_text(text)
    event_type = detect_event_type(text)
    window = EVENT_WINDOWS_MINUTES.get(event_type, EVENT_WINDOWS_MINUTES["general"])

    if _post_url(post) and _post_url(post) == event.get("canonical_url"):
        return True, "exact_url", 1.0

    if normalized and normalized == event.get("normalized_text"):
        # Exact text across VK audiences / repeated search queries is one content
        # origin, while every SourcePost remains attached to the event.
        return True, "same_text", 1.0

    if _platform(post) != _platform(event.get("representative_post") or {}):
        return _cross_platform_match(post, event)

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

    # Do not merge merely because two Google News items have the same publisher.
    # The RSS stream can contain unrelated articles from the same outlet minutes apart.
    return False, "no_match", similarity


def _event_id(posts: List[Dict[str, Any]]) -> str:
    keys = sorted(
        f"{p.get('source',{}).get('platform','')}:{p.get('source',{}).get('source_id','')}:{p.get('post',{}).get('id','')}"
        for p in posts
    )
    digest = hashlib.sha1("|".join(keys).encode("utf-8")).hexdigest()[:16]
    return f"evt_{digest}"


def _origin_key(post: Dict[str, Any]) -> str:
    """Approximate independent editorial origin, not raw audience/source id."""
    normalized = normalize_text(_text(post))
    if _platform(post) == "web_search":
        publisher = _publisher(post) or "unknown"
        return f"web:{publisher}:{normalized}"
    return f"{_platform(post)}:{normalized}"


def _independent_origin_count(posts: List[Dict[str, Any]]) -> int:
    return len({_origin_key(p) for p in posts if _text(p)})


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
    platforms = {_platform(p) for p in posts}
    urls = {_post_url(p) for p in posts if _post_url(p)}
    first_platform = _platform(first) or "unknown"

    discovery_path = []
    for p in ordered:
        platform = _platform(p) or "unknown"
        if platform not in discovery_path:
            discovery_path.append(platform)

    entities = extract_entities(canonical)
    origin_count = _independent_origin_count(posts)

    return {
        "event_id": _event_id(posts),
        "first_seen_at": first_ts,
        "last_seen_at": last_ts,
        "first_source": first_platform,
        "source_count": len(posts),
        "independent_source_count": origin_count,
        "raw_source_key_count": len(source_keys),
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
        "cluster_method": "deterministic_v5",
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
        reasons = list(event.get("cluster_reasons", []))
        if best_reason not in reasons:
            reasons.append(best_reason)
        updated["cluster_reasons"] = reasons
        updated["cluster_reason_last"] = best_reason
        updated["cluster_similarity_last"] = round(best_similarity, 4)
        events[best] = updated

    return events


def cross_platform_candidates(source_posts: Iterable[Dict[str, Any]], limit: int = 50) -> List[Dict[str, Any]]:
    """Return strongest WEB↔social pairs for diagnostic threshold tuning."""
    posts=list(source_posts)
    web_posts=[p for p in posts if _platform(p)=="web_search"]
    social_posts=[p for p in posts if _platform(p) in {"vk","telegram"}]
    candidates=[]
    for web in web_posts:
        left=meaningful_tokens(_match_text(web))
        if not left: continue
        for social in social_posts:
            if not _same_time(web,social,CROSS_PLATFORM_WINDOW_MINUTES): continue
            right=meaningful_tokens(_match_text(social))
            if not right: continue
            overlap, fuzzy_overlap = _semantic_overlap(left, right)
            matched_left = {a for a, _ in fuzzy_overlap} | overlap
            matched_right = {b for _, b in fuzzy_overlap} | overlap
            recall=len(matched_left)/len(left)
            precision=len(matched_right)/len(right)
            uncommon={t for t in matched_left if len(t)>=5 and t not in _STOPWORDS}
            seq=SequenceMatcher(None,normalize_text(_match_text(web)),normalize_text(_match_text(social))).ratio()
            ew=extract_entities(_match_text(web)); es=extract_entities(_match_text(social))
            numbers=set(ew["numbers"]) & set(es["numbers"])
            places=set(ew["places"]) & set(es["places"])
            type_match=ew["event_type"][0]==es["event_type"][0]
            fuzzy_count = len(fuzzy_overlap)
            score=(0.45*recall+0.15*precision+0.15*min(1.0,len(uncommon)/3)+0.10*min(1.0,len(numbers|places)/2)+0.10*int(type_match)+0.05*seq+0.05*min(1.0,fuzzy_count/2))
            if score<0.28: continue
            candidates.append({"score":round(score,4),"recall":round(recall,4),"precision":round(precision,4),"sequence":round(seq,4),"shared_tokens":sorted(uncommon)[:12],"shared_numbers":sorted(numbers),"shared_places":sorted(places),"event_type_match":type_match,"web":web,"social":social})
    candidates.sort(key=lambda x:(-x["score"],-x["recall"],-x["sequence"]))
    return candidates[:limit]
