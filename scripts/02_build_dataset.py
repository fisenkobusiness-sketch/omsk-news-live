# -*- coding: utf-8 -*-
"""02. RAW VK → единый нормализованный dataset двух аудиторий."""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    AUDIENCE_BY_SCREEN_NAME,
    DATASET_CSV,
    DATASET_JSON,
    RAW_OUTPUT,
)
from lib.analytics_core import (
    add_basic_metrics,
    calculate_scores,
    classify_posts,
)


def main():
    raw = json.loads(
        RAW_OUTPUT.read_text(encoding="utf-8")
    )

    posts = raw.get("posts", [])

    if not posts:
        raise RuntimeError(
            f"RAW пуст: {RAW_OUTPUT}"
        )

    counts = {}
    unknown = []

    for post in posts:
        screen_name = post.get(
            "group_screen_name"
        )

        audience = (
            post.get("audience_key")
            or AUDIENCE_BY_SCREEN_NAME.get(
                screen_name
            )
        )

        if not audience:
            unknown.append({
                "post_id": post.get("post_id"),
                "group_screen_name": screen_name,
            })
            continue

        post["audience_key"] = audience
        post["audience"] = audience
        counts[audience] = (
            counts.get(audience, 0) + 1
        )

    if unknown:
        raise RuntimeError(
            "Есть посты без audience_key: "
            f"{len(unknown)}. "
            f"Примеры: {unknown[:10]}"
        )

    add_basic_metrics(posts)
    classify_posts(posts)
    calculate_scores(posts)

    DATASET_JSON.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    DATASET_JSON.write_text(
        json.dumps(
            posts,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    fields = sorted({
        key
        for post in posts
        for key in post.keys()
    })

    with DATASET_CSV.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(posts)

    print(
        f"DATASET готов: {len(posts)} постов"
    )

    for audience, count in sorted(
        counts.items()
    ):
        print(
            f"  {audience}: {count}"
        )

    print(
        f"JSON: {DATASET_JSON}"
    )
    print(
        f"CSV:  {DATASET_CSV}"
    )


if __name__ == "__main__":
    main()
