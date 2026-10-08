# -*- coding: utf-8 -*-
"""Event-level freshness and spread metrics."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def _parse(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def enrich_event_freshness(event: Dict[str, Any], *, now: datetime | None = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    first = _parse(event.get("first_seen_at"))
    last = _parse(event.get("last_seen_at"))

    if first:
        event["freshness_age_minutes"] = round(max(0.0, (now - first).total_seconds() / 60), 1)
    else:
        event["freshness_age_minutes"] = None

    if first and last:
        event["spread_minutes"] = round(max(0.0, (last - first).total_seconds() / 60), 1)
    else:
        event["spread_minutes"] = None

    event["source_velocity"] = (
        round(event["source_count"] / max(event["spread_minutes"], 1.0), 4)
        if event["spread_minutes"] is not None
        else None
    )
    event["platform_velocity"] = (
        round(event["platform_count"] / max(event["spread_minutes"], 1.0), 4)
        if event["spread_minutes"] is not None
        else None
    )

    search_times = []
    social_times = []
    for post in event.get("source_posts", []):
        published = _parse((post.get("post") or {}).get("published_at"))
        platform = (post.get("source") or {}).get("platform")
        if not published:
            continue
        if platform == "web_search":
            search_times.append(published)
        elif platform in {"vk", "telegram"}:
            social_times.append(published)

    event["search_first_seen"] = min(search_times).isoformat(timespec="seconds").replace("+00:00", "Z") if search_times else None
    event["social_first_seen"] = min(social_times).isoformat(timespec="seconds").replace("+00:00", "Z") if social_times else None

    if search_times and social_times:
        delta = (min(social_times) - min(search_times)).total_seconds() / 60
        event["web_to_social_minutes"] = round(delta, 1)
    else:
        event["web_to_social_minutes"] = None

    return event
