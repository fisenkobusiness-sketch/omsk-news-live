# -*- coding: utf-8 -*-
"""Shared statistical primitives for topic analysis and prediction."""

from __future__ import annotations


def _post(member):
    """Return the raw post from either pipeline member representation."""
    if isinstance(member, dict) and isinstance(member.get("post"), dict):
        return member["post"]
    return member if isinstance(member, dict) else {}


def aggregate_topic_stats(members):
    """Aggregate the same counters for every pipeline stage."""
    posts = [_post(m) for m in (members or [])]
    views = sum(float(p.get("views", 0) or 0) for p in posts)
    reposts = sum(float(p.get("reposts", 0) or 0) for p in posts)
    likes = sum(float(p.get("likes", 0) or 0) for p in posts)
    comments = sum(float(p.get("comments", 0) or 0) for p in posts)
    return views, reposts, likes, comments


def newest_timestamp(members):
    """Return the newest valid post timestamp in a topic."""
    timestamps = []
    for member in members or []:
        ts = _post(member).get("timestamp")
        try:
            if ts is not None:
                timestamps.append(float(ts))
        except (TypeError, ValueError):
            continue
    return max(timestamps) if timestamps else None


def topic_age_hours(members, now_ts):
    """Age of the newest post, with a 15-minute safety floor."""
    ts = newest_timestamp(members)
    if ts is None:
        return 0.25
    return max(0.25, (now_ts - ts) / 3600.0)
