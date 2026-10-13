# -*- coding: utf-8 -*-
"""Build diagnostic NewsEvents from normalized discovery SourcePosts."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from events.clustering import cluster_source_posts
from events.editorial_event_type import classify_editorial_event_type
from events.freshness import enrich_event_freshness
from events.regional_relevance import assess_regional_relevance


SOURCE_POSTS_INPUT = ROOT / "data" / "normalized" / "source_posts.jsonl"
EVENTS_DIR = ROOT / "data" / "events"
EVENTS_OUTPUT = EVENTS_DIR / "news_events.jsonl"


def read_jsonl(path: Path):
    if not path.exists():
        raise FileNotFoundError(
            f"Не найден normalized discovery: {path}. "
            "Сначала запустите python run_pipeline.py --discovery"
        )
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(events):
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    with EVENTS_OUTPUT.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def main():
    source_posts = list(read_jsonl(SOURCE_POSTS_INPUT))

    regional_results = [
        (post, assess_regional_relevance(post))
        for post in source_posts
    ]
    accepted_posts = [
        post
        for post, regional in regional_results
        if regional["regional_status"] in {"REGION_CONFIRMED", "REGION_LIKELY"}
    ]
    rejected_count = len(source_posts) - len(accepted_posts)

    events = cluster_source_posts(accepted_posts)

    # Assign editorial categories only after clusters are finalized. The
    # clustering module keeps its own legacy type signal internally, so this
    # classification does not change event merging/splitting behavior.
    for event in events:
        editorial_type = classify_editorial_event_type(event.get("canonical_text") or "")
        event["event_type"] = editorial_type
        event["event_type_classifier"] = "editorial_headline_context_v1"
        entities = event.get("entities")
        if isinstance(entities, dict):
            entities["event_type"] = [editorial_type]

    events = [enrich_event_freshness(event) for event in events]
    write_jsonl(events)

    multi_source = sum(1 for event in events if event["source_count"] >= 2)
    cross_platform = sum(1 for event in events if event["platform_count"] >= 2)
    verified = sum(
        1 for event in events
        if (event.get("verification") or {}).get("state") != "UNVERIFIED"
    )

    print(f"SourcePost: {len(source_posts)}")
    print(f"Regional accepted: {len(accepted_posts)}")
    print(f"Regional rejected: {rejected_count}")
    print(f"NewsEvent: {len(events)}")
    print(f"Multi-source events: {multi_source}")
    print(f"Cross-platform events: {cross_platform}")
    event_type_counts = Counter(event.get("event_type", "general") for event in events)
    print(f"Event types: {dict(sorted(event_type_counts.items()))}")
    print(f"Event type classifier: editorial_headline_context_v1")
    print(f"Verified events: {verified}")
    print(f"NewsEvent сохранены: {EVENTS_OUTPUT}")


if __name__ == "__main__":
    main()
