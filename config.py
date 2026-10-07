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
# ДАННЫЕ
# ============================================================

RAW_DIR = BASE / "data" / "raw"
DATASET_DIR = BASE / "data" / "dataset"
ANALYTICS_DIR = BASE / "data" / "analytics"
MODEL_DIR = BASE / "data" / "model"
SCORING_DIR = BASE / "data" / "scoring"

RAW_OUTPUT = RAW_DIR / "omsk_vk_raw.json"

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
        DATASET_DIR,
        ANALYTICS_DIR,
        MODEL_DIR,
        SCORING_DIR,
        BASE / "secrets",
    ):
        path.mkdir(parents=True, exist_ok=True)


ensure_directories()
