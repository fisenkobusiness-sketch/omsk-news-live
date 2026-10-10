# -*- coding: utf-8 -*-
"""Conservative SourcePost -> NewsEvent clustering v20.

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
    "accident": (
        "дтп", "авар", "столкнов", "сбил", "наезд", "перевернул",
        "влетел", "влетела", "врезал", "врезалась", "столб",
    ),
    "fire": ("пожар", "загорел", "горит", "горел", "возгора"),
    "weather": ("снег", "дожд", "погода", "метел", "гололед", "мороз", "ветр"),
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
    # Окончания названия региона не должны считаться уникальными признаками новости.
    "омском", "омской", "омскую", "омскому", "омского", "омские", "омских", "омскими",
    "областной", "областного", "областному", "областной", "областных", "областную",
    "россия", "россии", "российский", "российская", "российского", "российской", "российские",
    "атака", "атаки", "атаке", "атакой", "атаку", "дрон", "дроны", "дронов",
    "бпла", "беспилотник", "беспилотники", "беспилотников", "беспилотная", "беспилотной",
    "губернатор", "губернатора", "губернатору", "хоценко", "виталия",
    "администрация", "администрации", "администрацию", "администрацией",
    "мэрия", "мэрии", "мэр", "мэра", "города", "городской", "городская", "городского",
    "страна", "страны", "стране", "страной", "странах",
    "район", "районе", "района", "району", "округ", "округа", "округе", "округу",
    # Дата публикации часто совпадает у совершенно разных новостей.
    "январь", "января", "январе", "февраль", "февраля", "феврале",
    "март", "марта", "марте", "апрель", "апреля", "апреле",
    "май", "мая", "мае", "июнь", "июня", "июне", "июль", "июля", "июле",
    "август", "августа", "августе", "сентябрь", "сентября", "сентябре",
    "октябрь", "октября", "октябре", "ноябрь", "ноября", "ноябре",
    "декабрь", "декабря", "декабре",
    "понедельник", "вторник", "среда", "среду", "среду", "четверг", "пятница", "пятницу",
    "суббота", "субботу", "воскресенье",
    # Формулировки из судебных новостей слишком часто встречаются в разных делах.
    "уголовное", "уголовного", "уголовный", "уголовном", "дело", "дела",
    "обвиняемый", "обвиняемого", "обвиняемая", "обвиняемой", "обвиняются",
    "подозреваемый", "подозреваемого", "подозреваемая", "подозреваемой",
    "судить", "суд", "суда", "судебный", "судебного", "прокуратура",
    "следствие", "следователи", "задержали", "задержан", "задержали",
    # Название спорта или общий формат мероприятия не равны одному событию.
    "хоккей", "хоккея", "хоккейный", "хоккейных", "матч", "матча", "матче", "матчей",
    "команда", "команды", "команде", "игра", "игры", "игре",
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
    "рублей", "миллиардов", "миллиона", "миллион", "тысяч",
    "водитель", "водителя", "автомобиль", "автомобиля",
    "машина", "машины", "проезд", "стоит", "услуги", "услуг",
    # Не использовать географию, даты и общеупотребительные конструкции как якоря.
    "омском", "омской", "омскую", "омскому", "омского", "омские", "омских", "омскими",
    "областной", "областного", "областному", "областных", "областную",
    "россии", "россия", "российский", "российская", "российского", "российской",
    "районе", "района", "округа", "округе", "округу",
    "января", "февраля", "марта", "апреля", "мая", "июня", "июля",
    "августа", "сентября", "октября", "ноября", "декабря",
    "понедельник", "вторник", "среда", "среду", "четверг", "пятница",
    "пятницу", "суббота", "субботу", "воскресенье",
    "уголовное", "уголовного", "уголовный", "уголовном", "дело", "дела",
    "обвиняемый", "обвиняемого", "обвиняемая", "обвиняемой", "обвиняются",
    "подозреваемый", "подозреваемого", "подозреваемая", "подозреваемой",
    "судить", "суд", "суда", "судебный", "судебного", "прокуратура",
    "следствие", "следователи", "задержали", "задержан",
    "хоккей", "хоккея", "хоккейный", "хоккейных", "матч", "матча", "матче",
    "матчей", "команда", "команды", "команде", "игра", "игры", "игре",
    # Messenger names, legal verbs, lighting terms, and siren terminology
    # are common topical words, not enough to identify one unique news event.
    "telegram", "телеграм", "канал", "канала", "каналу", "каналы", "каналов",
    "обвиняют", "обвиняет", "обвинение", "обвинения", "обвинять",
    "создателя", "задержали", "задержан", "пропаганде",
    "светильник", "светильника", "светильники", "светильников",
    "освещение", "освещения", "сквер", "сквере", "вандалы", "темноте",
    "сирена", "сирены", "сирен", "громкоговоритель", "громкоговорители",
    "оповещения", "оповещении", "проверка", "проверки", "системы",
    # A regional UAV attack can generate multiple unrelated follow-up stories.
    "атака", "атаки", "атаке", "атакой", "атаку", "дрон", "дроны", "дронов",
    "бпла", "беспилотник", "беспилотники", "беспилотников", "беспилотная",
    "беспилотной", "губернатор", "губернатора", "губернатору", "хоценко",
    "виталия", "администрация", "администрации", "администрацию", "администрацией",
    "мэрия", "мэрии", "мэр", "мэра", "города", "городской", "городская",
    "городского", "городской", "программа", "программы", "программой",
    "меры", "мер", "поставщик", "поставщика", "поставщику",
    # Standard greeting/opening phrases don't identify a unique news event.
    "доброе", "добрый", "добрая", "добрую", "добрыи", "утро", "привет",
    "приветствуем", "здравствуйте", "уважаемые", "дорогие", "читатели",
    "подписчики", "горожане",
}


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


def _phrase_tokens(value: str) -> List[str]:
    return [x for x in normalize_text(value).split() if x not in _STOPWORDS and len(x) >= 4]


def _phrase_anchor_matches(left_text: str, right_text: str) -> List[Tuple[str, str]]:
    """Find distinctive 2-word anchors, allowing Russian inflectional variants."""
    left = _phrase_tokens(left_text)
    right = _phrase_tokens(right_text)
    matches = []
    for i in range(len(left) - 1):
        a1, a2 = left[i], left[i + 1]
        if a1 in _MORPHOLOGY_GENERIC or a2 in _MORPHOLOGY_GENERIC:
            continue
        if max(len(a1), len(a2)) < 6:
            continue
        for j in range(len(right) - 1):
            b1, b2 = right[j], right[j + 1]
            if b1 in _MORPHOLOGY_GENERIC or b2 in _MORPHOLOGY_GENERIC:
                continue
            if max(len(b1), len(b2)) < 6:
                continue
            r1 = SequenceMatcher(None, a1, b1).ratio()
            r2 = SequenceMatcher(None, a2, b2).ratio()
            if r1 >= 0.86 and r2 >= 0.86:
                matches.append((f"{a1} {a2}", f"{b1} {b2}"))
    return matches


def _strong_phrase_anchor(left_text: str, right_text: str) -> bool:
    return bool(_phrase_anchor_matches(left_text, right_text))


def extract_numbers(value: str) -> set[str]:
    return set(_NUMBER_RE.findall(value or ""))


_ROAD_ACCIDENT_MARKERS = (
    "дтп", "столкнов", "сбил", "наезд", "перевернул",
    "пешеход", "водител", "автомобил", "машин",
    "влетел", "врезал", "столб", "опору освещения", "не справил",
)


def is_road_accident(value: str) -> bool:
    text = normalize_text(value)
    return any(marker in text for marker in _ROAD_ACCIDENT_MARKERS)


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


def _distinct_web_publisher_pair(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """Google News items from different publishers are cross-source candidates."""
    if _platform(left) != "web_search" or _platform(right) != "web_search":
        return False
    left_publisher = normalize_text(_publisher(left))
    right_publisher = normalize_text(_publisher(right))
    return bool(left_publisher and right_publisher and left_publisher != right_publisher)


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


def _strip_source_brand_suffix(value: str, post: Dict[str, Any]) -> str:
    """Remove a publisher label only when it is appended as a headline suffix."""
    result = str(value or "").strip()
    source = post.get("source") or {}
    meta = post.get("meta") or {}
    brands = [meta.get("publisher"), source.get("source_name")]
    for brand in brands:
        brand = str(brand or "").strip()
        if len(brand) < 3:
            continue
        pattern = r"\s*(?:[-–—|:]\s*)?" + re.escape(brand) + r"\s*$"
        result = re.sub(pattern, "", result, flags=re.IGNORECASE).strip()
    return result


def _match_text(post: Dict[str, Any]) -> str:
    """Text for matching, without appended publisher labels."""
    text = _strip_source_brand_suffix(_text(post), post)
    if _platform(post) == "web_search":
        description = str((post.get("meta") or {}).get("description") or "").strip()
        description = _strip_source_brand_suffix(description, post)
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
    # Canonical text can itself carry a Google News publisher suffix; remove it
    # using source metadata before considering the text for semantic identity.
    for source_post in event.get("source_posts") or []:
        canonical = _strip_source_brand_suffix(canonical, source_post)
    if canonical and canonical not in texts:
        texts.append(canonical)
    # Never concatenate all sources into one matching text. Doing so lets an
    # event accumulate unrelated terms and then match a third, unrelated post
    # through a "Frankenstein" union of tokens. Use one strongest source text.
    unique_texts = list(dict.fromkeys(texts))
    return max(unique_texts, key=len) if unique_texts else canonical


def _identity_text(post: Dict[str, Any]) -> str:
    """Choose a headline/lead for matching; long article bodies are supporting context."""
    text = _match_text(post)
    raw = _strip_source_brand_suffix(_text(post), post)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) > 1:
        # Publisher posts normally place the headline before a blank line.
        # If the opening is boilerplate (greeting/anonymity label), keep that
        # opening as identity rather than matching the body to an unrelated story.
        return lines[0][:240]
    # Search results usually contain only a headline; full social texts without
    # line breaks are limited to their lead to avoid matching on distant details.
    return text[:240]


def _event_identity_text(event: Dict[str, Any]) -> str:
    identities = [
        _identity_text(post)
        for post in event.get("source_posts") or []
        if _identity_text(post)
    ]
    return max(identities, key=len) if identities else str(event.get("canonical_text") or "")[:240]


# Нерелевантные сами по себе слова при сравнении двух ДТП.
_ACCIDENT_GENERIC_ANCHORS = _MORPHOLOGY_GENERIC | {
    "дтп", "авария", "аварии", "происшествие", "происшествия",
    "пострадал", "пострадала", "пострадали", "дети", "детей",
    "ребенок", "ребёнок", "мальчик", "девочка", "травмы", "травмами",
    "полиция", "сообщение", "предварительно", "установлено",
    "госпитализировали", "больницу", "пассажир", "пассажиры",
    "сегодня", "вчера", "около", "часов", "минут", "водитель",
    "водителя", "женщина", "мужчина", "управление", "управлением",
}
_LOCATION_CUE_RE = re.compile(
    r"\b(?:улица|улице|улицы|ул|проспект|проспекте|просп|шоссе|"
    r"переулок|бульвар|набережная|площадь|остановка|остановке|остановки|остановку)\s+"
    r"([а-яё0-9-]+(?:\s+[а-яё0-9-]+){0,3})\b",
    re.I,
)
_NUMBERED_STREET_RE = re.compile(r"\b\d{1,3}\s+(?:лет|я)\s+[а-яё]{4,}\b", re.I)
_LANDMARK_ANCHOR_RE = re.compile(
    r"\b(?:континент|заозерн\w*|куйбышев\w*|лазо|юбилейн\w*)\b", re.I
)
_HOUSE_NUMBER_RE = re.compile(
    r"\b(?:дом(?:а)?|д\.?)\s*(?:№\s*)?(\d+[а-яё]?(?:к\d+)?)\b",
    re.I,
)
_LOCATION_STOP_WORDS = {
    "не", "вчера", "сегодня", "завтра", "около", "районе", "дом", "дома",
    "после", "перед", "когда", "где", "который", "которая", "которые",
    "совершила", "совершил", "врезалась", "врезался", "не", "и", "а", "по",
    "в", "на", "у", "с", "из", "до", "для", "что", "как",
}


def _location_anchors(value: str) -> set[str]:
    """Извлекает осторожные текстовые якоря улиц и названий вида «70 лет Октября»."""
    text = normalize_text(value)
    anchors = {match.group(0) for match in _NUMBERED_STREET_RE.finditer(text)}
    anchors.update(match.group(0) for match in _LANDMARK_ANCHOR_RE.finditer(text))
    anchors.update(match.group(1) for match in _HOUSE_NUMBER_RE.finditer(text))
    for match in _LOCATION_CUE_RE.finditer(text):
        words = match.group(1).split()
        phrase = []
        for word in words:
            if word in _LOCATION_STOP_WORDS:
                break
            phrase.append(word)
        if phrase:
            # Keep both the full street/stop phrase and its first meaningful
            # word so "ул. Заозёрная" matches "остановка 7-я Заозёрная".
            if phrase and re.fullmatch(r"\d{1,3}-я", phrase[0]) and len(phrase) > 1:
                phrase = phrase[1:]
            anchors.add(" ".join(phrase[:3]))
            anchors.add(phrase[0])
    return {anchor for anchor in anchors if len(anchor) >= 5}


def _same_accident_location_and_details(left_text: str, right_text: str) -> bool:
    """Подсказка для дублей ДТП: одна улица плюс несколько отличительных деталей."""
    shared_locations = _location_anchors(left_text) & _location_anchors(right_text)
    # A road-accident match requires a shared concrete location/landmark.
    # Similar accident vocabulary, ages, dates or numbers alone are not enough.
    if not shared_locations:
        return False

    left_tokens = meaningful_tokens(left_text)
    right_tokens = meaningful_tokens(right_text)
    shared = left_tokens & right_tokens

    # Без совпавшего конкретного адреса или ориентира не склеиваем ДТП по
    # набору общих категорий ("автомобиль", "пострадавший", "столб"):
    # это приводит к смешению разных происшествий в разных местах.

    # Не считать сам адрес отличительными деталями: иначе любые два ДТП
    # на одной улице могли бы ошибочно склеиться.
    location_tokens = {
        token
        for anchor in shared_locations
        for token in anchor.split()
    }
    distinctive = {
        token for token in shared - location_tokens
        if len(token) >= 5 and token not in _ACCIDENT_GENERIC_ANCHORS
        and not token.isdigit()
    }
    shared_numbers = extract_numbers(left_text) & extract_numbers(right_text)
    location_numbers = {
        number
        for anchor in shared_locations
        for number in extract_numbers(anchor)
    }
    non_location_numbers = shared_numbers - location_numbers

    # Для коротких формулировок вроде «не справилась с управлением» достаточно
    # одного отличительного действия, если совпали ещё и несколько числовых
    # деталей (например, время, возраст и данные пострадавших).
    return len(distinctive) >= 2 or (
        len(distinctive) >= 1 and len(non_location_numbers) >= 2
    )


def _is_scheduled_siren_test(value: str) -> bool:
    text = normalize_text(value)
    tokens = text.split()
    local = any(token.startswith(("омск", "омич")) for token in tokens)
    alert_system = any(token.startswith(("сирен", "громкоговорител", "оповещ", "систем")) for token in tokens)
    planned = any(token.startswith(("провер", "планов", "тестирован")) for token in tokens)
    return local and alert_system and planned


def _traffic_summary_period(value: str) -> str | None:
    """Return a period key for traffic-statistics posts, not individual crashes."""
    text = normalize_text(value)
    is_summary = any(
        marker in text
        for marker in (
            "итоги суток", "подвели итоги", "итоги работы", "статистика дтп",
            "показатели аварийности", "состояние аварийности",
        )
    )
    has_traffic_context = any(
        marker in text for marker in ("дтп", "аварийн", "госавтоинспек", "дорожн")
    )
    if not (is_summary and has_traffic_context):
        return None

    months = re.search(r"\bза\s+(\d{1,2})\s+месяц", text)
    if months:
        return f"months:{months.group(1)}"
    if re.search(r"\b(?:суток|минувшие сутки|прошедшие сутки)\b", text):
        return "daily"
    quarters = re.search(r"\bза\s+(\d{1,2})\s+квартал", text)
    if quarters:
        return f"quarters:{quarters.group(1)}"
    if re.search(r"\bза\s+год\b|\bгодовые итоги\b", text):
        return "yearly"
    return "summary:unspecified"


def _cross_platform_match(post: Dict[str, Any], event: Dict[str, Any]) -> Tuple[bool, str, float]:
    """Match a short web-search headline to a longer social post conservatively."""
    other = event.get("representative_post") or {}
    same_source = _source_key(post) == _source_key(other)
    if same_source and not _distinct_web_publisher_pair(post, other):
        return False, "same_source", 0.0

    if not _same_time(post, other, CROSS_PLATFORM_WINDOW_MINUTES):
        return False, "cross_platform_time_window", 0.0

    left_text = _match_text(post)
    right_text = _event_match_text(event)
    left_identity = _identity_text(post)
    right_identity = _event_identity_text(event)

    # Aggregated road-safety statistics are separate editorial events from
    # individual crashes. Also keep reports for different reporting periods
    # separate (e.g. daily totals vs results for nine months), even when they
    # share many accident-related words and the same regional publisher.
    left_period = _traffic_summary_period(left_text)
    right_period = _traffic_summary_period(right_text)
    if (left_period is None) != (right_period is None):
        return False, "traffic_summary_vs_incident", 0.0
    if left_period and right_period and left_period != right_period:
        return False, "traffic_summary_period_mismatch", 0.0

    # Do ordinary semantic matching on headlines/leads, not the full article
    # bodies. Body mentions of a governor, city administration, roads or a UAV
    # attack often describe context rather than the story's actual subject.
    left = meaningful_tokens(left_identity)
    right = meaningful_tokens(right_identity)

    if not left or not right:
        return False, "cross_platform_no_tokens", 0.0

    overlap, fuzzy_overlap = _semantic_overlap(left, right)
    matched_left = {a for a, _ in fuzzy_overlap} | overlap
    matched_right = {b for _, b in fuzzy_overlap} | overlap
    recall = len(matched_left) / len(left)
    precision = len(matched_right) / len(right)
    seq = SequenceMatcher(None, normalize_text(left_identity), normalize_text(right_identity)).ratio()

    current_entities = extract_entities(left_identity)
    event_entities = extract_entities(right_identity)
    numbers = set(current_entities["numbers"]) & set(event_entities.get("numbers", []))
    places = set(current_entities["places"]) & set(event_entities.get("places", []))
    type_match = current_entities["event_type"][0] == event_entities["event_type"][0]

    # Strong accident identity (same street and distinctive details) outranks
    # headline wording and event-type labels, which are often inconsistent.
    if (
        is_road_accident(left_text)
        and is_road_accident(right_text)
        and _same_accident_location_and_details(left_text, right_text)
    ):
        return True, "same_accident_location_and_details", 0.94

    # Identity needs a semantic anchor, not merely shared digits (such as the
    # current year) or a broad regional location like Омск/Омская область.
    uncommon_overlap = {
        t for t in matched_left
        if len(t) >= 5 and t not in _STOPWORDS and t not in _MORPHOLOGY_GENERIC
    }
    fuzzy_count = len(fuzzy_overlap)
    phrase_anchors = _phrase_anchor_matches(left_identity, right_identity)
    specific_places = {p for p in places if p not in {"омск", "омская", "область", "город", "центр"}}
    strong_anchor = bool(specific_places or phrase_anchors or len(uncommon_overlap) >= 2)

    if recall >= 0.78 and strong_anchor and type_match:
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
    # Accidents are especially collision-prone: "водитель / мужчина / насмерть"
    # can describe many unrelated ДТП. For accident stories, morphology must
    # have a concrete event identity anchor: a shared number, specific place,
    # or distinctive two-word phrase. This is intentionally stricter than the
    # generic cross-platform rule.
    if (
        type_match
        and current_entities["event_type"][0] == "accident"
        and is_road_accident(_match_text(post))
        and is_road_accident(_event_match_text(event))
    ):
        accident_identity_anchor = bool(numbers or specific_places or phrase_anchors)
        if not accident_identity_anchor:
            return False, "accident_no_identity_anchor", max(recall, seq)

    # Require either two distinctive exact anchors or two distinctive
    # inflectional anchors, plus the same event type.
    morphology_anchor = (
        len(exact_anchors) >= 2
        or fuzzy_anchor_count >= 2
        or bool(phrase_anchors)
    )
    if type_match and morphology_anchor and strong_anchor:
        score = 0.45 * recall + 0.20 * min(1.0, (len(exact_anchors) + fuzzy_anchor_count) / 3) + 0.20 * int(type_match) + 0.15 * seq
        return True, "morphology_match", score

    if recall >= 0.62 and type_match and strong_anchor and (numbers or specific_places or phrase_anchors):
        score = 0.50 * recall + 0.20 * int(type_match) + 0.20 * min(1.0, len(numbers | specific_places) / 2) + 0.10 * seq
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

    event_match_text = _event_match_text(event)
    if (
        _is_scheduled_siren_test(text)
        and _is_scheduled_siren_test(event_match_text)
        and _same_time(post, event["representative_post"], CROSS_PLATFORM_WINDOW_MINUTES)
    ):
        return True, "same_scheduled_siren_test", 0.95

    if (
        is_road_accident(text)
        and is_road_accident(event_match_text)
        and _same_accident_location_and_details(text, event_match_text)
    ):
        return True, "same_accident_location_and_details", 0.94

    representative = event.get("representative_post") or {}
    if (
        _platform(post) != _platform(representative)
        or _source_key(post) != _source_key(representative)
        or _distinct_web_publisher_pair(post, representative)
    ):
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
        "cluster_method": "deterministic_v20",
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