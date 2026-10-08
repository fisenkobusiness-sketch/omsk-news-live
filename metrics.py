# -*- coding: utf-8 -*-
"""Shared topic metrics and small-sample stabilization."""

from __future__ import annotations

# Empirical priors calibrated from the 2026-10-08 149-topic baseline.
PRIOR_VIEWS = 2182.0
PRIOR_ENGAGEMENT_PER_1000 = 5.2172351103321395
PRIOR_COMMENTS_PER_1000 = 0.5007776088746414
PRIOR_REPOSTS_PER_1000 = 0.2829720262054196
PRIOR_VELOCITY_PER_HOUR = 262.8275109170306

def aggregate_topic_stats(members):
    members = members or []
    views = sum(float(m.get("views", 0) or 0) for m in members)
    reposts = sum(float(m.get("reposts", 0) or 0) for m in members)
    likes = sum(float(m.get("likes", 0) or 0) for m in members)
    comments = sum(float(m.get("comments", 0) or 0) for m in members)
    return views, reposts, likes, comments

def topic_age_hours(members, now_ts):
    members = members or []
    if not members:
        return 0.25
    timestamp = members[0].get("timestamp")
    try:
        timestamp = float(timestamp)
    except (TypeError, ValueError):
        return 0.25
    return max(0.25, (now_ts - timestamp) / 3600)

def stabilized_rate_per_1000(value, views, prior_rate, prior_views=PRIOR_VIEWS):
    views = max(float(views or 0), 0.0)
    value = max(float(value or 0), 0.0)
    prior_value = prior_rate * prior_views / 1000.0
    return ((value + prior_value) / (views + prior_views)) * 1000.0

def engagement_rate(likes, comments, reposts, views):
    return stabilized_rate_per_1000(likes + comments * 2 + reposts * 4, views, PRIOR_ENGAGEMENT_PER_1000)

def comment_rate(comments, views):
    return stabilized_rate_per_1000(comments, views, PRIOR_COMMENTS_PER_1000)

def repost_rate(reposts, views):
    return stabilized_rate_per_1000(reposts, views, PRIOR_REPOSTS_PER_1000)


def velocity_signal(views, age_hours):
    """Smooth current view velocity using a median-based saturation curve."""
    age_hours = max(float(age_hours or 0), 0.25)
    rate = max(float(views or 0), 0.0) / age_hours
    return 100.0 * rate / (rate + PRIOR_VELOCITY_PER_HOUR)
