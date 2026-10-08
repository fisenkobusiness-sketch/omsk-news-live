# -*- coding: utf-8 -*-
"""Shared topic metrics used by analysis and prediction stages."""

from __future__ import annotations


def aggregate_topic_stats(members):
    """Return consistent aggregate counters for one clustered topic."""
    members = members or []
    views = sum(float(m.get("views", 0) or 0) for m in members)
    reposts = sum(float(m.get("reposts", 0) or 0) for m in members)
    likes = sum(float(m.get("likes", 0) or 0) for m in members)
    comments = sum(float(m.get("comments", 0) or 0) for m in members)
    return views, reposts, likes, comments


def topic_age_hours(members, now_ts):
    """Age of the newest member post, with a 15-minute floor."""
    members = members or []
    if not members:
        return 0.25
    timestamp = members[0].get("timestamp")
    try:
        timestamp = float(timestamp)
    except (TypeError, ValueError):
        return 0.25
    return max(0.25, (now_ts - timestamp) / 3600)
