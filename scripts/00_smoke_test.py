# -*- coding: utf-8 -*-
"""Быстрая проверка целостности проекта после git pull."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    AUDIENCES,
    EDITORIAL_MODEL,
    AUDIENCE_PROFILES,
    SCORING_INPUT,
)
from lib.analytics_core import (
    classify_one,
    prepare_fresh_classification,
)
from lib.audience_router import (
    extract_event_meta,
)
from collectors.search import build_google_news_search_url


def main():
    assert AUDIENCES == ("golos", "zhest")

    search_url = build_google_news_search_url(
        query="Омск",
        when="6h",
    )
    assert "news.google.com/rss/search" in search_url
    assert "when%3A6h" in search_url

    classification = classify_one({
        "title": "На трассе Омск—Красноярка погибли три человека в ДТП",
        "text": "",
        "attachment_count": 0,
    })
    event = extract_event_meta(
        {
            "title": "На трассе Омск—Красноярка погибли три человека в ДТП",
            "text": "",
        },
        {
            "fresh_event_strength": 58.0,
            "classification": classification,
        },
    )
    assert event["death_count"] == 3, event

    prepared = prepare_fresh_classification({
        "title": "На трассе Омск—Красноярка погибли три человека в ДТП",
        "text": "",
        "attachment_count": 0,
    })
    assert "incident" in prepared["mechanisms"]

    for path in (
        EDITORIAL_MODEL,
        AUDIENCE_PROFILES,
        SCORING_INPUT,
    ):
        if not path.exists():
            raise AssertionError(
                f"Не найден обязательный файл: {path}"
            )

        json.loads(
            path.read_text(encoding="utf-8")
        )

    print("SMOKE TEST: OK")
    print("  audiences:", ", ".join(AUDIENCES))
    print("  death_count:", event["death_count"])
    print("  required artifacts: OK")


if __name__ == "__main__":
    main()
