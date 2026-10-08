# -*- coding: utf-8 -*-
"""Сбор свежей поисковой выдачи новостей Омска."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    SEARCH_OUTPUT,
    WEB_SEARCH_COUNTRY,
    WEB_SEARCH_DEFAULT_WHEN,
    WEB_SEARCH_ENABLED,
    WEB_SEARCH_LANGUAGE,
    WEB_SEARCH_MAX_ITEMS,
    WEB_SEARCH_QUERIES,
    WEB_SEARCH_REQUEST_DELAY,
)
from collectors.search import (
    GoogleNewsRSSCollector,
    SearchQuery,
)


def log(message: str) -> None:
    print(
        f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}",
        flush=True,
    )


def build_queries():
    return [
        SearchQuery(
            query_id=item["id"],
            query=item["query"],
            label=item.get("label", ""),
        )
        for item in WEB_SEARCH_QUERIES
    ]


def main() -> None:
    if not WEB_SEARCH_ENABLED:
        log("WEB SEARCH отключён через WEB_SEARCH_ENABLED=0.")
        return

    queries = build_queries()

    collector = GoogleNewsRSSCollector(
        language=WEB_SEARCH_LANGUAGE,
        country=WEB_SEARCH_COUNTRY,
        default_when=WEB_SEARCH_DEFAULT_WHEN,
        max_items=WEB_SEARCH_MAX_ITEMS,
        request_delay=WEB_SEARCH_REQUEST_DELAY,
    )

    log(
        f"Поисковая выдача: {len(queries)} запросов, "
        f"окно {WEB_SEARCH_DEFAULT_WHEN}"
    )

    items = collector.collect(queries)

    payload = {
        "version": "1.0",
        "platform": "web_search",
        "collector": "google-news-rss",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "queries": [
            {
                "id": query.query_id,
                "query": query.query,
                "label": query.label,
            }
            for query in queries
        ],
        "posts_count": len(items),
        "posts": items,
    }

    SEARCH_OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    SEARCH_OUTPUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    log(
        f"RAW поиска сохранён: {SEARCH_OUTPUT} "
        f"({len(items)} уникальных материалов)"
    )


if __name__ == "__main__":
    main()
