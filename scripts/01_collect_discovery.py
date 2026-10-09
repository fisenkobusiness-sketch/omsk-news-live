# -*- coding: utf-8 -*-
"""Discovery layer: VK + Web Search -> normalized SourcePost JSONL.

This is intentionally separate from the legacy collectors. It can be run
without changing the historical VK dataset or scoring pipeline.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    TELEGRAM_CHANNELS,
    TELEGRAM_WEB_ENABLED,
    TELEGRAM_WEB_TIMEOUT,
    TELEGRAM_WEB_REQUEST_DELAY,
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
from collectors.telegram_web import TelegramPublicWebCollector


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


def collect_telegram_public():
    """Collect public Telegram previews into a separate human-review stream."""
    if not TELEGRAM_WEB_ENABLED or not TELEGRAM_CHANNELS:
        return []

    collector = TelegramPublicWebCollector(
        TELEGRAM_CHANNELS,
        timeout=TELEGRAM_WEB_TIMEOUT,
        request_delay=TELEGRAM_WEB_REQUEST_DELAY,
    )
    items = collector.collect()

    for label, count in collector.source_counts.items():
        print(f"  Telegram public: {label} — {count} постов за сегодня", flush=True)

    for error in collector.errors:
        print(
            "WARN: Telegram source skipped: "
            f"{error['label']} (@{error['username']}): {error['error']}",
            flush=True,
        )

    return items


def write_jsonl_to(items, output_path):
    NORMALIZED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
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


def write_jsonl(items):
    write_jsonl_to(items, SOURCE_POSTS_OUTPUT)



def merge_telegram_review_jsonl(items, output_path):
    """Keep today's public Telegram posts across repeated discovery runs."""
    today_omsk = (
        datetime.now(timezone.utc) + timedelta(hours=6)
    ).date()
    merged = {}

    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                    post = item.get("post") or {}
                    published_at = post.get("published_at")
                    if not published_at:
                        continue
                    published = datetime.fromisoformat(
                        published_at.replace("Z", "+00:00")
                    )
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    local_date = (
                        published.astimezone(timezone.utc)
                        + timedelta(hours=6)
                    ).date()
                    if local_date != today_omsk:
                        continue
                    key = post.get("url") or post.get("id")
                    if key:
                        merged[str(key)] = item
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue

    for item in items:
        post = item.get("post") or {}
        key = post.get("url") or post.get("id")
        if key:
            merged[str(key)] = item

    ordered = sorted(
        merged.values(),
        key=lambda item: (
            (item.get("post") or {}).get("published_at") or ""
        ),
        reverse=True,
    )
    write_jsonl_to(ordered, output_path)
    return ordered



def main():
    started = datetime.now(timezone.utc)

    vk_items = VKDiscoveryCollector().collect()
    search_items = collect_search()
    telegram_public_items = collect_telegram_public()

    # Telegram's public preview is written separately for human editorial
    # review; it is not merged into the SourcePost stream used by scoring.
    telegram_output = NORMALIZED_DIR / "telegram_public_posts.jsonl"
    items = [
        *vk_items,
        *search_items,
    ]

    write_jsonl(items)
    telegram_public_items = merge_telegram_review_jsonl(
        telegram_public_items,
        telegram_output,
    )

    print(
        f"Discovery SourcePost сохранён: "
        f"{SOURCE_POSTS_OUTPUT}",
        flush=True,
    )
    print(
        f"VK: {len(vk_items)} | "
        f"Telegram public (отдельная лента): {len(telegram_public_items)} | "
        f"Web Search: {len(search_items)} | "
        f"Всего в основном discovery: {len(items)}",
        flush=True,
    )
    print(
        f"Telegram public posts сохранены отдельно: {telegram_output}",
        flush=True,
    )
    print(
        "Сбор завершён: "
        f"{started.isoformat(timespec='seconds')}",
        flush=True,
    )


if __name__ == "__main__":
    main()
