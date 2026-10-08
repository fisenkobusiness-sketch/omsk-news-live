# -*- coding: utf-8 -*-
"""Human-readable diagnostic report for NewsEvent clustering."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INPUT = ROOT / "data" / "events" / "news_events.jsonl"
REPORT = ROOT / "data" / "events" / "clustering_report.txt"


def read_events():
    if not INPUT.exists():
        raise FileNotFoundError(
            f"Не найден {INPUT}. Сначала запустите: python run_pipeline.py --events"
        )
    with INPUT.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def source_label(post):
    source = post.get("source") or {}
    return f"{source.get('platform','?')} / {source.get('source_name','?')}"


def post_time(post):
    return (post.get("post") or {}).get("published_at") or "time-unknown"


def post_text(post):
    text = (post.get("post") or {}).get("text") or ""
    return " ".join(text.split())


def main():
    events = read_events()
    multi = [e for e in events if e.get("source_count", 0) >= 2]
    cross = [e for e in multi if e.get("platform_count", 0) >= 2]

    reason_counter = Counter()
    for event in multi:
        reasons = event.get("cluster_reasons") or [event.get("cluster_reason_last", "single_source")]
        reason_counter.update(reasons)

    lines = []
    lines.append("NEWS EVENT CLUSTERING REPORT")
    lines.append("=" * 80)
    lines.append(f"Всего NewsEvent: {len(events)}")
    lines.append(f"Multi-source events: {len(multi)}")
    lines.append(f"Cross-platform events: {len(cross)}")
    lines.append(
        f"Events with independent origins >=2: "
        f"{sum(1 for e in events if e.get('independent_source_count', 0) >= 2)}"
    )
    lines.append("")
    lines.append("Причины объединения (накопленные):")
    for reason, count in reason_counter.most_common():
        lines.append(f"  {reason}: {count}")
    lines.append("")
    lines.append("CROSS-PLATFORM EVENTS")
    lines.append("=" * 80)

    if not cross:
        lines.append("Нет cross-platform событий.")

    for number, event in enumerate(
        sorted(cross, key=lambda e: (-e.get("independent_source_count", 0), e.get("event_id", ""))),
        start=1,
    ):
        lines.append("")
        lines.append(
            f"[{number}] {event.get('event_id')} | "
            f"type={event.get('event_type')} | "
            f"sources={event.get('source_count')} | "
            f"independent={event.get('independent_source_count')} | "
            f"platforms={event.get('platform_count')} | "
            f"reasons={','.join(event.get('cluster_reasons') or [])}"
        )
        lines.append(f"canonical: {post_text({'post': {'text': event.get('canonical_text','')}})}")
        lines.append(f"discovery_path: {' -> '.join(event.get('discovery_path') or [])}")
        lines.append("-" * 80)
        for index, post in enumerate(event.get("source_posts") or [], start=1):
            lines.append(
                f"{index}. {source_label(post)} | {post_time(post)} | "
                f"url={(post.get('post') or {}).get('url') or 'n/a'}"
            )
            lines.append(f"   {post_text(post)[:500]}")

    lines.append("")
    lines.append("ALL MULTI-SOURCE EVENTS")
    lines.append("=" * 80)

    for number, event in enumerate(
        sorted(multi, key=lambda e: (-e.get("source_count", 0), e.get("event_id", ""))),
        start=1,
    ):
        lines.append("")
        lines.append(
            f"[{number}] {event.get('event_id')} | "
            f"type={event.get('event_type')} | "
            f"sources={event.get('source_count')} | "
            f"independent={event.get('independent_source_count')} | "
            f"platforms={event.get('platform_count')} | "
            f"reasons={','.join(event.get('cluster_reasons') or [])}"
        )
        lines.append(f"canonical: {post_text({'post': {'text': event.get('canonical_text','')}})}")
        lines.append(f"discovery_path: {' -> '.join(event.get('discovery_path') or [])}")
        lines.append("-" * 80)

        for index, post in enumerate(event.get("source_posts") or [], start=1):
            lines.append(
                f"{index}. {source_label(post)} | {post_time(post)} | "
                f"url={(post.get('post') or {}).get('url') or 'n/a'}"
            )
            lines.append(f"   {post_text(post)[:500]}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"NewsEvent: {len(events)}")
    print(f"Multi-source events: {len(multi)}")
    print(f"Cross-platform events: {len(cross)}")
    print(f"Events with independent origins >=2: {sum(1 for e in events if e.get('independent_source_count', 0) >= 2)}")
    print("Причины:")
    for reason, count in reason_counter.most_common():
        print(f"  {reason}: {count}")
    print(f"Отчёт: {REPORT}")


if __name__ == "__main__":
    main()
