# -*- coding: utf-8 -*-
"""VK collector for the unified discovery layer.

This module deliberately does not replace scripts/01_collect_vk.py.
The legacy collector keeps its historical RAW schema for backwards
compatibility; this collector produces normalized SourcePost objects.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

from config import (
    API_VERSION,
    GROUPS,
    DISCOVERY_VK_SOURCES,
    PAGE_SIZE,
    REQUEST_DELAY,
    VK_TOKEN_FILE,
)
from normalization.source_post import make_source_post


class VKDiscoveryCollector:
    def __init__(
        self,
        *,
        max_posts: int = 200,
        page_size: int = PAGE_SIZE,
        request_delay: float = REQUEST_DELAY,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        self.max_posts = max_posts
        self.page_size = page_size
        self.request_delay = request_delay
        self.timeout = timeout
        self.session = session or requests.Session()

    @staticmethod
    def _read_secret(path, env_name: str) -> str:
        value = os.getenv(env_name, "").strip()
        if value:
            return value

        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value

        raise RuntimeError(
            f"Не найден секрет: {path}. "
            f"Положите ключ в этот файл или задайте {env_name}."
        )

    def _token(self) -> str:
        return self._read_secret(VK_TOKEN_FILE, "VK_SERVICE_KEY")

    def _call(self, method: str, token: str, **params: Any) -> Dict[str, Any]:
        params["access_token"] = token
        params["v"] = API_VERSION

        response = self.session.get(
            f"https://api.vk.com/method/{method}",
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            error = data["error"]
            raise RuntimeError(
                f"VK API {method}: "
                f"{error.get('error_msg', error)}"
            )

        return data["response"]

    def _resolve_group(
        self,
        token: str,
        audience_key: str,
        cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        response = self._call(
            "groups.getById",
            token,
            group_ids=cfg["screen_name"],
            fields="name,screen_name,members_count",
        )
        groups = response.get("groups", [])
        if not groups:
            raise RuntimeError(
                f"VK не вернул группу {cfg['screen_name']}"
            )

        group = groups[0]
        return {
            "id": int(group["id"]),
            "name": group.get("name", cfg["label"]),
            "screen_name": group.get(
                "screen_name",
                cfg["screen_name"],
            ),
            "members_count": int(
                group.get("members_count", 0) or 0
            ),
            "audience_key": audience_key,
        }

    @staticmethod
    def _normalize(
        group: Dict[str, Any],
        item: Dict[str, Any],
    ) -> Dict[str, Any]:
        owner_id = int(item["owner_id"])
        post_id = int(item["id"])
        timestamp = int(item.get("date", 0) or 0)

        attachments = item.get("attachments") or []
        media_types = [
            str(a.get("type", "unknown"))
            for a in attachments
            if isinstance(a, dict)
        ]

        published_at = None
        if timestamp:
            published_at = (
                datetime.fromtimestamp(
                    timestamp,
                    tz=timezone.utc,
                )
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )

        return make_source_post(
            platform="vk",
            kind="community_post",
            source_id=str(group["id"]),
            source_name=group["name"],
            source_url=(
                f"https://vk.ru/{group['screen_name']}"
            ),
            post_id=f"{owner_id}_{post_id}",
            post_url=(
                f"https://vk.ru/wall{owner_id}_{post_id}"
            ),
            published_at=published_at,
            text=item.get("text", "") or "",
            media_types=media_types,
            views=int(
                (item.get("views") or {}).get("count", 0)
            ) if item.get("views") is not None else None,
            likes=int(
                (item.get("likes") or {}).get("count", 0)
            ) if item.get("likes") is not None else None,
            comments=int(
                (item.get("comments") or {}).get("count", 0)
            ) if item.get("comments") is not None else None,
            reposts=int(
                (item.get("reposts") or {}).get("count", 0)
            ) if item.get("reposts") is not None else None,
            collection_extra={
                "collector_version": "vk-discovery/1.0",
                "audience_key": group["audience_key"],
                "group_members": group["members_count"],
                "is_pinned": bool(item.get("is_pinned", 0)),
                "marked_as_ads": bool(
                    item.get("marked_as_ads", False)
                ),
            },
            meta={
                "owner_id": owner_id,
                "post_id": post_id,
                "copyright": item.get("copyright"),
            },
        )

    def collect(self) -> List[Dict[str, Any]]:
        token = self._token()
        result: List[Dict[str, Any]] = []

        for cfg in DISCOVERY_VK_SOURCES:
            group = self._resolve_group(
                token,
                "discovery",
                cfg,
            )

            offset = 0
            collected = 0

            while collected < self.max_posts:
                count = min(
                    self.page_size,
                    self.max_posts - collected,
                )

                response = self._call(
                    "wall.get",
                    token,
                    owner_id=-abs(group["id"]),
                    count=count,
                    offset=offset,
                    filter="owner",
                )
                items = response.get("items", [])
                if not items:
                    break

                result.extend(
                    self._normalize(group, item)
                    for item in items
                )

                collected += len(items)
                offset += len(items)

                total = int(
                    response.get("count", 0) or 0
                )
                if len(items) < count or (
                    total and offset >= total
                ):
                    break

                if self.request_delay > 0:
                    time.sleep(self.request_delay)

        return result
