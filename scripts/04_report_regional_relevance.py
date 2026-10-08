# -*- coding: utf-8 -*-
"""Диагностический отчёт региональной релевантности SourcePost."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from events.regional_relevance import assess_regional_relevance

INPUT = ROOT / "data" / "normalized" / "source_posts.jsonl"


def main():
    posts = [
        json.loads(line)
        for line in INPUT.open(encoding="utf-8")
        if line.strip()
    ]

    results = []
    for post in posts:
        result = assess_regional_relevance(post)
        results.append((post, result))

    counts = Counter(result["regional_status"] for _, result in results)
    print("=" * 70)
    print("REGIONAL RELEVANCE — DIAGNOSTIC")
    print("=" * 70)
    print(f"SourcePost: {len(results)}")
    print(f"CONFIRMED: {counts['REGION_CONFIRMED']}")
    print(f"LIKELY:    {counts['REGION_LIKELY']}")
    print(f"REJECTED:  {counts['REGION_REJECTED']}")
    print()

    likely = [
        (post, result)
        for post, result in results
        if result["regional_status"] == "REGION_LIKELY"
    ]

    print("LIKELY:")
    for index, (post, result) in enumerate(likely, start=1):
        source = post.get("source") or {}
        body = post.get("post") or {}
        meta = post.get("meta") or {}
        print(
            f"{index}. "
            f"[{meta.get('query_id')}] "
            f"{meta.get('publisher') or source.get('source_name')} | "
            f"{body.get('text')} | "
            f"score={result['regional_relevance']} | "
            f"reason={','.join(result['regional_reasons'])}"
        )

    print()

    rejected = [
        (post, result)
        for post, result in results
        if result["regional_status"] == "REGION_REJECTED"
    ]

    print("REJECTED:")
    for index, (post, result) in enumerate(rejected, start=1):
        source = post.get("source") or {}
        body = post.get("post") or {}
        meta = post.get("meta") or {}
        print(
            f"{index}. "
            f"[{meta.get('query_id')}] "
            f"{meta.get('publisher') or source.get('source_name')} | "
            f"{body.get('text')} | "
            f"reason={','.join(result['regional_reasons'])}"
        )

    print()
    print("STATUS BY PLATFORM:")
    by_platform = {}
    for post, result in results:
        platform = (post.get("source") or {}).get("platform")
        by_platform.setdefault(platform, Counter())[result["regional_status"]] += 1
    for platform, counter in by_platform.items():
        print(platform, dict(counter))


if __name__ == "__main__":
    main()
