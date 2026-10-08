# -*- coding: utf-8 -*-
"""Единый внутренний формат публикации любого discovery-источника."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional


SCHEMA_VERSION = "1.0"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )


def make_source_post(
    *,
    platform: str,
    kind: str,
    source_id: str,
    source_name: str,
    source_url: Optional[str],
    post_id: str,
    post_url: Optional[str],
    published_at: Optional[str],
    edited_at: Optional[str] = None,
    text: str = "",
    media_types: Optional[Iterable[str]] = None,
    views: Optional[int] = None,
    likes: Optional[int] = None,
    comments: Optional[int] = None,
    reposts: Optional[int] = None,
    collection_extra: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Создаёт SourcePost без подмены отсутствующих метрик нулями."""
    types = [
        str(item)
        for item in (media_types or [])
        if item is not None
    ]

    collection = {
        "collected_at": utc_now_iso(),
        "collector_version": "source-post/1.0",
    }

    if collection_extra:
        collection.update(collection_extra)

    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "platform": platform,
            "kind": kind,
            "source_id": str(source_id),
            "source_name": source_name,
            "source_url": source_url,
        },
        "post": {
            "id": str(post_id),
            "url": post_url,
            "published_at": published_at,
            "edited_at": edited_at,
            "text": text or "",
        },
        "media": {
            "has_media": bool(types),
            "types": types,
            "count": len(types),
        },
        "signals": {
            "views": views,
            "likes": likes,
            "comments": comments,
            "reposts": reposts,
        },
        "collection": collection,
        "meta": meta or {},
    }
