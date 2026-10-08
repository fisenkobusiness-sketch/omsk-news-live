# -*- coding: utf-8 -*-
"""Discovery layer: VK + Web Search -> normalized SourcePost JSONL.

This is intentionally separate from the legacy collectors. It can be run
without changing the historical VK dataset or scoring pipeline.
"""
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
from collectors.vk import VKDiscoveryCollector


NORMALIZED_DIR = ROOT / "data" / "normalized"
SOURCE_POSTS_OUTPUT = NORMALIZED_DIR / "source_posts.jsonl"


def build_search_queries():
    return [
        SearchQuery(
            query_id=item["id"],
            query=item["query"],
            label=item.get("label", ""),
        )
        for item in WEB_SEARCH_QUERIES
    ]


def collect_search():
    if not WEB_SEARCH_ENABLED:
        return []

    collector = GoogleNewsRSSCollector(
        language=WEB_SEARCH_LANGUAGE,
        country=WEB_SEARCH_COUNTRY,
        default_when=WEB_SEARCH_DEFAULT_WHEN,
        max_items=WEB_SEARCH_MAX_ITEMS,
        request_delay=WEB_SEARCH_REQUEST_DELAY,
    )
    items = collector.collect(build_search_queries())

    for error in collector.errors:
        print(
            "WARN: search query skipped: "
            f"{error['query_id']}: {error['error']}",
            flush=True,
        )

    return items


def write_jsonl(items):
    NORMALIZED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with SOURCE_POSTS_OUTPUT.open(
        "w",
        encoding="utf-8",
    ) as handle:
        for item in items:
            handle.write(
                json.dumps(
                    item,
                    ensure_ascii=False,
                )
                + "\n"
            )


def main():
    started = datetime.now(timezone.utc)

    vk_items = VKDiscoveryCollector().collect()
    search_items = collect_search()

    items = [
        *vk_items,
        *search_items,
    ]

    write_jsonl(items)

    print(
        f"Discovery SourcePost сохранён: "
        f"{SOURCE_POSTS_OUTPUT}",
        flush=True,
    )
    print(
        f"VK: {len(vk_items)} | "
        f"Web Search: {len(search_items)} | "
        f"Всего: {len(items)}",
        flush=True,
    )
    print(
        "Сбор завершён: "
        f"{started.isoformat(timespec='seconds')}",
        flush=True,
    )


if __name__ == "__main__":
    main()
