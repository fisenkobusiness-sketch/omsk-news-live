# -*- coding: utf-8 -*-
"""03. Раздельная историческая аналитика двух аудиторий."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    AUDIENCE_PROFILES,
    AUDIENCE_REPORT,
    AUDIENCES,
    AUDIENCE_BY_GROUP_ID,
    DATASET_JSON,
)
from lib.analytics_core import (
    compact_post,
    content_type_report,
    mechanism_combinations,
    mechanism_report,
    stable_mechanism_combinations,
    temporal_oos_combination_validation,
    temporal_stability_analysis,
)
from lib.audience_router import build_profiles


MECHANISMS = [
    "locality",
    "incident",
    "conflict",
    "human_story",
    "animal",
    "weather",
    "unusual",
    "humor",
    "shock",
    "fear",
    "positive_emotion",
    "usefulness",
    "help_request",
    "visual_hook",
    "question_cta",
    "emoji_hook",
    "media",
]


def build_one_report(posts, audience):
    rows = [
        post for post in posts
        if post.get("audience") == audience
    ]

    if not rows:
        raise RuntimeError(
            f"Не найдены посты аудитории {audience}"
        )

    return {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds"),
        "audience": audience,
        "posts_analyzed": len(rows),
        "content_types": content_type_report(rows),
        "mechanisms": mechanism_report(rows),
        "mechanism_combinations": mechanism_combinations(
            rows,
            MECHANISMS,
            min_posts=20,
            top_n=100,
        ),
        "stable_mechanism_combinations":
            stable_mechanism_combinations(
                rows,
                MECHANISMS,
                min_posts=50,
                top_n=100,
            ),
        "temporal_stability":
            temporal_stability_analysis(
                rows,
                MECHANISMS,
                periods=4,
                top_n_per_period=20,
            ),
        "temporal_oos_validation":
            temporal_oos_combination_validation(
                rows,
                MECHANISMS,
                periods=4,
                top_n_train=30,
                min_train_posts=20,
                min_test_posts=5,
                min_periods_present=2,
            ),
        "top_potential": [
            compact_post(post)
            for post in sorted(
                rows,
                key=lambda x: x.get(
                    "potential", 0
                ),
                reverse=True,
            )[:50]
        ],
        "top_virality": [
            compact_post(post)
            for post in sorted(
                rows,
                key=lambda x: x.get(
                    "virality", 0
                ),
                reverse=True,
            )[:50]
        ],
        "top_approval": [
            compact_post(post)
            for post in sorted(
                rows,
                key=lambda x: x.get(
                    "approval", 0
                ),
                reverse=True,
            )[:50]
        ],
    }


def main():
    posts = json.loads(
        DATASET_JSON.read_text(
            encoding="utf-8"
        )
    )

    for post in posts:
        audience = post.get("audience")

        if not audience:
            audience = AUDIENCE_BY_GROUP_ID.get(
                int(post.get("group_id", 0) or 0)
            )

        if audience not in AUDIENCES:
            raise RuntimeError(
                "Не удалось определить аудиторию "
                f"для post_id={post.get('post_id')}"
            )

        post["audience"] = audience
        post["audience_key"] = audience

    reports = {
        audience: build_one_report(
            posts,
            audience,
        )
        for audience in AUDIENCES
    }

    # На этапе 03 профиль строится по observed history.
    # На этапе 04 он будет пересобран относительно той же модели,
    # которая используется для fresh scoring.
    profiles = build_profiles(
        posts,
        models=None,
        audiences=AUDIENCES,
    )

    report = {
        "version": "3.0",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds"),
        "posts_analyzed": len(posts),
        "audiences": reports,
        "audience_profiles": profiles,
        "methodology_note": (
            "Raw score разных аудиторий не сравнивается напрямую. "
            "Для routing используется percentile-fit внутри "
            "исторической шкалы конкретной аудитории."
        ),
    }

    AUDIENCE_REPORT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    AUDIENCE_REPORT.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    AUDIENCE_PROFILES.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    AUDIENCE_PROFILES.write_text(
        json.dumps(
            profiles,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"Аналитика готова: {AUDIENCE_REPORT}"
    )

    for audience in AUDIENCES:
        print(
            f"  {audience}: "
            f"{reports[audience]['posts_analyzed']} постов"
        )


if __name__ == "__main__":
    main()
