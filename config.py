# -*- coding: utf-8 -*-
"""Единая конфигурация проекта «Анализатор контента»."""

from pathlib import Path
import os


BASE = Path(__file__).resolve().parent


# ============================================================
# АУДИТОРИИ
# ============================================================

GROUPS = {
    "golos": {
        "id": 133335843,
        "screen_name": "omskgolos",
        "label": "Голос Омска",
        "url": "https://vk.com/omskgolos",
    },
    "zhest": {
        "id": 76091195,
        "screen_name": "ghest_omska",
        "label": "Новости Омска | Жесть",
        "url": "https://vk.com/ghest_omska",
    },
}

AUDIENCES = tuple(GROUPS.keys())

AUDIENCE_BY_SCREEN_NAME = {
    cfg["screen_name"]: key
    for key, cfg in GROUPS.items()
}

AUDIENCE_BY_GROUP_ID = {
    int(cfg["id"]): key
    for key, cfg in GROUPS.items()
}


# ============================================================
# ОБРАТНАЯ СОВМЕСТИМОСТЬ СО СТАРЫМИ МОДУЛЯМИ
# ============================================================

GROUP_SCREEN_NAME = GROUPS["golos"]["screen_name"]
GROUP_URL = GROUPS["golos"]["url"]

EXTRA_GROUP_SCREEN_NAMES = [
    cfg["screen_name"]
    for key, cfg in GROUPS.items()
    if key != "golos"
]


# ============================================================
# VK
# ============================================================

API_VERSION = "5.199"

MAX_POSTS = int(os.getenv("VK_MAX_POSTS", "2000"))
PAGE_SIZE = int(os.getenv("VK_PAGE_SIZE", "100"))
REQUEST_DELAY = float(os.getenv("VK_REQUEST_DELAY", "0.34"))

VK_TOKEN_FILE = BASE / "secrets" / "vk_service_key.txt"
GITHUB_TOKEN_FILE = BASE / "secrets" / "github_token.txt"

# ============================================================
# WEB SEARCH / GOOGLE NEWS
# ============================================================

WEB_SEARCH_ENABLED = (
    os.getenv("WEB_SEARCH_ENABLED", "1").strip() != "0"
)
WEB_SEARCH_LANGUAGE = (
    os.getenv("WEB_SEARCH_LANGUAGE", "ru").strip() or "ru"
)
WEB_SEARCH_COUNTRY = (
    os.getenv("WEB_SEARCH_COUNTRY", "RU").strip() or "RU"
)
WEB_SEARCH_DEFAULT_WHEN = (
    os.getenv("WEB_SEARCH_DEFAULT_WHEN", "6h").strip()
    or "6h"
)
WEB_SEARCH_MAX_ITEMS = int(
    os.getenv("WEB_SEARCH_MAX_ITEMS", "100")
)
WEB_SEARCH_REQUEST_DELAY = float(
    os.getenv("WEB_SEARCH_REQUEST_DELAY", "0.25")
)

# Базовые поисковые профили. К каждому запросу автоматически
# добавляется WEB_SEARCH_DEFAULT_WHEN.
WEB_SEARCH_QUERIES = [
    {
        "id": "omsk_general",
        "query": "Омск",
        "label": "Омск — общий поток",
    },
    {
        "id": "omsk_oblast",
        "query": "Омская область",
        "label": "Омская область — общий поток",
    },
    {
        "id": "omsk_incident",
        "query": "Омск происшествие",
        "label": "Происшествия",
    },
    {
        "id": "omsk_dtp",
        "query": "Омск ДТП",
        "label": "ДТП",
    },
    {
        "id": "omsk_fire",
        "query": "Омск пожар",
        "label": "Пожары",
    },
    {
        "id": "omsk_court",
        "query": "Омск суд",
        "label": "Суды",
    },
    {
        "id": "omsk_transport",
        "query": "Омск транспорт",
        "label": "Транспорт",
    },
    {
        "id": "omsk_social",
        "query": "Омск выплаты OR льготы OR тарифы",
        "label": "Социальные и тарифные темы",
    },
    {
        "id": "omsk_schools",
        "query": "Омск школы",
        "label": "Школы и дети",
    },
    {
        "id": "omsk_weather",
        "query": "Омск погода снег дождь",
        "label": "Погода",
    },
    {
        "id": "om1",
        "query": "Омск site:om1.ru",
        "label": "Поиск по Om1",
    },
    {
        "id": "kvnews",
        "query": "Омск site:kvnews.ru",
        "label": "Поиск по Коммерческим вестям",
    },
    {
        "id": "superomsk",
        "query": "Омск site:superomsk.ru",
        "label": "Поиск по SuperOmsk",
    },
    {
        "id": "ngs55",
        "query": "Омск site:ngs55.ru",
        "label": "Поиск по NGS55",
    },
    {
        "id": "omskinform",
        "query": "Омск site:omskinform.ru",
        "label": "Поиск по Омск-информ",
    },
]



# ============================================================
# DISCOVERY LAYER
# ============================================================

# Registry is metadata only: collectors do not contain hard-coded
# editorial source quality decisions.
DISCOVERY_SOURCES = {
    "vk": {
        "source_type": "social",
        "source_quality": "platform",
        "verification_level": "UNVERIFIED",
    },
    "telegram": {
        "source_type": "social",
        "source_quality": "platform",
        "verification_level": "UNVERIFIED",
    },
    "web_search": {
        "source_type": "search",
        "source_quality": "discovery",
        "verification_level": "UNVERIFIED",
    },
}

# Telegram credentials are intentionally read only from environment/local
# secrets by collectors. No active credentials belong in this file.
TELEGRAM_ENABLED = (
    os.getenv("TELEGRAM_ENABLED", "0").strip() != "0"
)
TELEGRAM_MAX_MESSAGES = int(
    os.getenv("TELEGRAM_MAX_MESSAGES", "200")
)
# Public Telegram web previews work without MTProto API credentials.
# Keep Telegram posts separate from model/scoring inputs.
TELEGRAM_WEB_ENABLED = (
    os.getenv("TELEGRAM_WEB_ENABLED", "1").strip() != "0"
)
TELEGRAM_WEB_TIMEOUT = float(
    os.getenv("TELEGRAM_WEB_TIMEOUT", "15")
)
TELEGRAM_WEB_REQUEST_DELAY = float(
    os.getenv("TELEGRAM_WEB_REQUEST_DELAY", "0.25")
)
TELEGRAM_SESSION = (
    os.getenv("TELEGRAM_SESSION", "").strip()
    or str(BASE / "secrets" / "telegram")
)

# Channel registry is configuration, not collector code. Keep usernames
# without @. It can be populated when MTProto credentials are configured.
TELEGRAM_CHANNELS = []


# ============================================================
# DISCOVERY DONOR REGISTRY
# ============================================================

DISCOVERY_VK_SOURCES = [
    {"screen_name": "inci55", "label": "Инцидент Омск"},
    {"screen_name": "omsk_live", "label": "Омск Live"},
    {"screen_name": "dushalady", "label": "dushalady"},
    {"screen_name": "omsk_group", "label": "Омск"},
    {"screen_name": "omsk_glavniy", "label": "Омск главный | Новости"},
    {"screen_name": "12kanalomsk", "label": "12 Канал | Новости Омска"},
    {"screen_name": "omsk_reg", "label": "Сегодня в Омске"},
    {"screen_name": "club233315760", "label": "club233315760"},
    {"screen_name": "ghest_omsk", "label": "Жесть Омска"},
    {"screen_name": "omsk_online", "label": "ОМСК ОНЛАЙН"},
    {"screen_name": "55gibdd", "label": "55 ГИБДД"},
    {"screen_name": "ouromsk", "label": "НАШ ГОРОД ОМСК"},
    {"screen_name": "live_omck", "label": "Я живу [В] Омске"},
    {"screen_name": "omsk_pubs", "label": "Омск паблики"},
    {"screen_name": "la_omsk", "label": "Леди Омск"},
    {"screen_name": "chp55", "label": "ЧП Омск"},
    {"screen_name": "tipical_omsk", "label": "Вкратце | Омск!"},
    {"screen_name": "aomsk", "label": "Аварийный Омск"},
    {"screen_name": "omsk_vk", "label": "Омск ВК"},
    {"screen_name": "spletniki55", "label": "О чём говорят в Омске"},
    {"screen_name": "region_omsk55", "label": "Омск | Регион-55 | REGIK55"},
    {"screen_name": "regio55", "label": "Регион 55 | ЧС Омск"},
    {"screen_name": "1oomestomska", "label": "100 необычных мест Омска"},
    {"screen_name": "v_omsk", "label": "Омск сегодня"},
    {"screen_name": "tvoy_omsk", "label": "Твой Омск"},
    {"screen_name": "van_omsk", "label": "Омск"},
    {"screen_name": "om1_omsk", "label": "Om1.ru: новости Омска"},
    {"screen_name": "lovepub55", "label": "Новости Омск"},
]

TELEGRAM_CHANNELS = [
    {"username": "Om1_Omsk", "label": "Om1"},
    {"username": "HocenkoVP", "label": "Хоценко"},
    {"username": "kanal12omsk", "label": "12 Канал"},
    {"username": "omsk_smi", "label": "Новости Омска и области"},
    {"username": "chp_55", "label": "ЧП Омск"},
    {"username": "zhest_omsk_55", "label": "Жесть Омска"},
    {"username": "region_omsk55", "label": "Регион 55"},
    {"username": "aomsk", "label": "Аварийный Омск"},
    {"username": "ghest_omsk", "label": "Жесть Омска"},
    {"username": "gorod55ru", "label": "Город55"},
    {"username": "vestiomsk", "label": "Вести Омск"},
    {"username": "vkratce_omsk", "label": "Вкратце | Омск"},
    {"username": "omskkoroche", "label": "Омсккороче"},
    {"username": "ngs55news", "label": "NGS55"},
    {"username": "shelest_sn", "label": "Шелест"},
    {"username": "newsomsk", "label": "Новости Омска"},
    {"username": "omsk_police", "label": "Омская полиция"},
    {"username": "omskonelove", "label": "Омск One Love"},
    {"username": "minzdrav_55", "label": "Минздрав Омской области"},
    {"username": "omskiyavangard", "label": "Авангард"},
    {"username": "omsktop1", "label": "Омск с огоньком"},
    {"username": "omskinform_news", "label": "Омск-информ"},
    {"username": "forumomskcom", "label": "Омский Форум"},
    {"username": "forumomsknew", "label": "Новый Омский форум"},
]

# ============================================================
# ДАННЫЕ
# ============================================================

RAW_DIR = BASE / "data" / "raw"
DATASET_DIR = BASE / "data" / "dataset"
ANALYTICS_DIR = BASE / "data" / "analytics"
MODEL_DIR = BASE / "data" / "model"
SCORING_DIR = BASE / "data" / "scoring"

RAW_OUTPUT = RAW_DIR / "omsk_vk_raw.json"

SEARCH_RAW_DIR = RAW_DIR / "search"
SEARCH_OUTPUT = SEARCH_RAW_DIR / "omsk_search_raw.json"


DATASET_JSON = DATASET_DIR / "omsk_vk_dataset.json"
DATASET_CSV = DATASET_DIR / "omsk_vk_dataset.csv"

AUDIENCE_REPORT = ANALYTICS_DIR / "audience_report.json"
AUDIENCE_PROFILES = MODEL_DIR / "audience_profiles.json"
EDITORIAL_MODEL = MODEL_DIR / "editorial_model.json"

SCORING_INPUT = SCORING_DIR / "fresh_news.json"
SCORING_OUTPUT = SCORING_DIR / "scored_news.json"


# ============================================================
# SCORING
# ============================================================

PRIORITY_THRESHOLD = 62.0
TAKE_THRESHOLD = 55.0
RESERVE_THRESHOLD = 52.0


# ============================================================
# GITHUB
# ============================================================

GITHUB_OWNER = os.getenv("GITHUB_OWNER", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()
GITHUB_BRANCH = os.getenv(
    "GITHUB_BRANCH",
    "audience-router",
).strip() or "audience-router"

GITHUB_DIRS = {
    "golos": "audience_analytics/vk/golos",
    "zhest": "audience_analytics/vk/zhest",
}

# Совместимость со старой структурой 06_publish_github.py.
AUDIENCE_REPORTS = {
    key: ANALYTICS_DIR / key / "audience_report.json"
    for key in AUDIENCES
}

EDITORIAL_MODELS = {
    key: MODEL_DIR / key / "editorial_model.json"
    for key in AUDIENCES
}


# ============================================================
# СЛУЖЕБНОЕ
# ============================================================

def ensure_directories():
    for path in (
        RAW_DIR,
        SEARCH_RAW_DIR,
        DATASET_DIR,
        ANALYTICS_DIR,
        MODEL_DIR,
        SCORING_DIR,
        BASE / "secrets",
    ):
        path.mkdir(parents=True, exist_ok=True)


ensure_directories()
