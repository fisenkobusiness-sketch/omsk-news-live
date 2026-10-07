# -*- coding: utf-8 -*-
"""06. Необязательная публикация результатов в GitHub.

Запускать только после настройки GITHUB_OWNER/GITHUB_REPO/GITHUB_TOKEN.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    AUDIENCE_REPORTS,
    DATASET_CSV,
    DATASET_JSON,
    EDITORIAL_MODELS,
    GITHUB_BRANCH,
    GITHUB_DIRS,
    GITHUB_OWNER,
    GITHUB_REPO,
    GITHUB_TOKEN_FILE,
    RAW_OUTPUT,
    SCORING_OUTPUT,
)


def read_token():
    value = os.getenv(
        "GITHUB_TOKEN",
        "",
    ).strip()

    if value:
        return value

    if GITHUB_TOKEN_FILE.exists():
        return GITHUB_TOKEN_FILE.read_text(
            encoding="utf-8"
        ).strip()

    return ""


def request(url, method="GET", body=None):
    token = read_token()

    if not token:
        raise RuntimeError(
            "Не задан GITHUB_TOKEN."
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": (
            "application/vnd.github+json"
        ),
        "Content-Type": "application/json",
        "User-Agent": (
            "omsk-audience-analytics"
        ),
    }

    data = (
        json.dumps(
            body,
            ensure_ascii=False,
        ).encode("utf-8")
        if body is not None
        else None
    )

    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )

    with urllib.request.urlopen(
        req,
        timeout=30,
    ) as response:
        return json.load(response)


def get_sha(api, path):
    try:
        return request(
            f"{api}/contents/{path}"
            f"?ref={GITHUB_BRANCH}"
        ).get("sha")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def put(path, content, message):
    api = (
        "https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}"
    )

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("ascii")

    sha = get_sha(
        api,
        path,
    )

    body = {
        "message": message,
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }

    if sha:
        body["sha"] = sha

    return request(
        f"{api}/contents/{path}",
        method="PUT",
        body=body,
    )


def main():
    if not GITHUB_OWNER or not GITHUB_REPO:
        raise RuntimeError(
            "Настройте GITHUB_OWNER и "
            "GITHUB_REPO в переменных среды."
        )

    if not read_token():
        raise RuntimeError(
            "Настройте GITHUB_TOKEN."
        )

    common = [
        (
            RAW_OUTPUT,
            "omsk_vk_raw.json",
        ),
        (
            DATASET_JSON,
            "dataset.json",
        ),
        (
            DATASET_CSV,
            "dataset.csv",
        ),
        (
            SCORING_OUTPUT,
            "scored_news.json",
        ),
    ]

    published = 0

    for local, remote_name in common:
        if not local.exists():
            print(
                f"⚠ Нет файла: {local}"
            )
            continue

        put(
            f"audience_analytics/vk/common/"
            f"{remote_name}",
            local.read_text(
                encoding="utf-8"
            ),
            f"Update common VK analytics: "
            f"{remote_name}",
        )

        published += 1
        print(
            f"GitHub: common/{remote_name}"
        )

    for audience, remote_dir in GITHUB_DIRS.items():
        files = [
            (
                AUDIENCE_REPORTS[audience],
                "audience_report.json",
            ),
            (
                EDITORIAL_MODELS[audience],
                "editorial_model.json",
            ),
        ]

        for local, remote_name in files:
            if not local.exists():
                print(
                    f"⚠ Нет файла: {local}"
                )
                continue

            put(
                f"{remote_dir}/"
                f"{remote_name}",
                local.read_text(
                    encoding="utf-8"
                ),
                f"Update {audience} analytics: "
                f"{remote_name}",
            )

            published += 1
            print(
                f"GitHub: {audience}/"
                f"{remote_name}"
            )

    print(
        f"✓ Опубликовано файлов: {published}"
    )


if __name__ == "__main__":
    main()
