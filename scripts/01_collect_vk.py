# -*- coding: utf-8 -*-
"""01. Сбор исторических постов VK по всем аудиториям."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    API_VERSION,
    AUDIENCE_BY_SCREEN_NAME,
    GROUPS,
    MAX_POSTS,
    PAGE_SIZE,
    RAW_OUTPUT,
    REQUEST_DELAY,
    VK_TOKEN_FILE,
)


def log(message):
    print(
        f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}",
        flush=True,
    )


def read_secret(path, env_name):
    value = os.getenv(env_name, "").strip()

    if value:
        return value

    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value

    raise RuntimeError(
        f"Не найден секрет: {path}\n"
        f"Положите ключ в этот файл или задайте переменную {env_name}."
    )


def read_vk_token():
    return read_secret(VK_TOKEN_FILE, "VK_SERVICE_KEY")


def vk_call(method, token, **params):
    params["access_token"] = token
    params["v"] = API_VERSION

    response = requests.get(
        f"https://api.vk.com/method/{method}",
        params=params,
        timeout=30,
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


def resolve_groups(token):
    groups = []

    for audience_key, cfg in GROUPS.items():
        screen_name = cfg["screen_name"]

        response = vk_call(
            "groups.getById",
            token,
            group_ids=screen_name,
            fields="name,screen_name,members_count",
        )

        resolved = response.get("groups", [])

        if not resolved:
            raise RuntimeError(
                f"VK не вернул группу {screen_name}"
            )

        group = resolved[0]

        groups.append({
            "id": int(group["id"]),
            "name": group.get("name", cfg["label"]),
            "screen_name": group.get(
                "screen_name",
                screen_name,
            ),
            "members_count": int(
                group.get("members_count", 0) or 0
            ),
            "audience_key": audience_key,
        })

    return groups


def normalize_post(group, item):
    owner_id = int(item["owner_id"])
    post_id = int(item["id"])
    timestamp = int(item.get("date", 0) or 0)

    likes = int(
        (item.get("likes") or {}).get("count", 0) or 0
    )
    comments = int(
        (item.get("comments") or {}).get("count", 0) or 0
    )
    reposts = int(
        (item.get("reposts") or {}).get("count", 0) or 0
    )
    views = int(
        (item.get("views") or {}).get("count", 0) or 0
    )

    attachments = item.get("attachments") or []

    attachment_types = [
        str(a.get("type", "unknown"))
        for a in attachments
        if isinstance(a, dict)
    ]

    return {
        "group_id": group["id"],
        "group_name": group["name"],
        "group_screen_name": group["screen_name"],
        "audience_key": AUDIENCE_BY_SCREEN_NAME.get(
            group["screen_name"],
            group.get("audience_key"),
        ),
        "group_members": group["members_count"],
        "post_id": post_id,
        "owner_id": owner_id,
        "date": datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        ).isoformat(timespec="seconds"),
        "timestamp": timestamp,
        "text": item.get("text", "") or "",
        "likes": likes,
        "comments": comments,
        "reposts": reposts,
        "views": views,
        "url": f"https://vk.ru/wall{owner_id}_{post_id}",
        "attachment_count": len(attachments),
        "attachment_types": attachment_types,
        "is_pinned": bool(item.get("is_pinned", 0)),
        "marked_as_ads": bool(
            item.get("marked_as_ads", False)
        ),
        "copyright": item.get("copyright"),
    }


def fetch_history(token, group):
    posts = []
    offset = 0

    log(
        f"Собираем историю: {group['name']} "
        f"(@{group['screen_name']})"
    )

    while len(posts) < MAX_POSTS:
        remaining = MAX_POSTS - len(posts)
        count = min(PAGE_SIZE, remaining)

        response = vk_call(
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

        posts.extend(
            normalize_post(group, item)
            for item in items
        )

        offset += len(items)

        total = int(
            response.get("count", 0) or 0
        )

        shown_total = (
            min(total, MAX_POSTS)
            if total
            else MAX_POSTS
        )

        log(
            f"  Получено {len(posts)} / "
            f"{shown_total}"
        )

        if len(items) < count:
            break

        if total and offset >= total:
            break

        time.sleep(REQUEST_DELAY)

    return posts


def main():
    token = read_vk_token()
    groups = resolve_groups(token)

    all_posts = []
    group_results = []

    for group in groups:
        posts = fetch_history(token, group)
        all_posts.extend(posts)

        group_results.append({
            "group": group,
            "posts_count": len(posts),
        })

    payload = {
        "version": "3.0",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "groups": groups,
        "group_results": group_results,
        "posts_count": len(all_posts),
        "posts": all_posts,
        "group": groups[0] if groups else None,
    }

    RAW_OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    RAW_OUTPUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    log(
        f"RAW сохранён: {RAW_OUTPUT} "
        f"({len(all_posts)} постов)"
    )

    for result in group_results:
        group = result["group"]
        log(
            f"  {group['name']} "
            f"(@{group['screen_name']}): "
            f"{result['posts_count']} постов"
        )


if __name__ == "__main__":
    main()
