# -*- coding: utf-8 -*-
"""04. Построение независимых редакторских моделей двух аудиторий."""
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
    EDITORIAL_MODEL,
)
from lib.analytics_core import (
    build_editorial_model_v1,
    editorial_backtest,
)
from lib.audience_router import build_profiles, chronological_routing_oos


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
                f"Неизвестная аудитория "
                f"для post_id={post.get('post_id')}"
            )

        post["audience"] = audience

    report = json.loads(
        AUDIENCE_REPORT.read_text(
            encoding="utf-8"
        )
    )

    models = {}
    backtests = {}

    for audience in AUDIENCES:
        rows = [
            post for post in posts
            if post.get("audience") == audience
        ]

        if not rows:
            raise RuntimeError(
                f"Нет истории для {audience}"
            )

        aud_report = report[
            "audiences"
        ][audience]

        model = build_editorial_model_v1(
            rows,
            aud_report["mechanisms"],
            aud_report[
                "temporal_oos_validation"
            ],
        )

        model["audience"] = audience
        model["audience_label"] = (
            next(
                (
                    post.get("group_name")
                    for post in rows
                    if post.get("group_name")
                ),
                audience,
            )
        )

        models[audience] = model

        backtests[audience] = editorial_backtest(
            rows,
            model,
            top_n=50,
        )

    # Хронологический OOS-тест разделителя выполняется отдельно от
    # построения production-моделей и не меняет их автоматически.
    routing_oos = chronological_routing_oos(
        posts,
        audiences=AUDIENCES,
        periods=4,
    )

    # Критически важно:
    # профили теперь строятся на score, который выдаёт ИМЕННО эта модель.
    # Так raw шкалы двух пабликов не смешиваются.
    profiles = build_profiles(
        posts,
        models=models,
        audiences=AUDIENCES,
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

    if isinstance(routing_oos, dict):
        routing_oos["event_dominance"] = {
            "method": "hybrid_explicit_components_plus_strength",
            "single_death": "dominant_level_1",
            "two_or_more_deaths": "dominant_level_2_plus",
            "child_accident": "dominant_when_strength>=40",
            "quarantine_disease": "dominant_when_strength>=40",
            "pollution_environment": "dominant_when_strength>=45",
            "fire_multiple_injuries": "dominant_when_strength>=40",
            "generic_strength": "dominant_when_strength>=70",
        }

    output = {
        "version": "3.0",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds"),
        "models": models,
        "backtests": backtests,
        "audience_routing_oos": routing_oos,
        "routing_note": (
            "Raw score моделей независим. "
            "Для выбора аудитории использовать audience_fit."
        ),
    }

    EDITORIAL_MODEL.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    EDITORIAL_MODEL.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Дополнительно сохраняем отдельные модели/отчёты,
    # чтобы их можно было публиковать или смотреть независимо.
    for audience in AUDIENCES:
        report_path = (
            AUDIENCE_REPORT.parent
            / audience
            / "audience_report.json"
        )
        model_path = (
            EDITORIAL_MODEL.parent
            / audience
            / "editorial_model.json"
        )

        report_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        model_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        report_path.write_text(
            json.dumps(
                report["audiences"][audience],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        model_path.write_text(
            json.dumps(
                models[audience],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    print(
        f"Модели готовы: {EDITORIAL_MODEL}"
    )

    for audience in AUDIENCES:
        model = models[audience]
        print(
            f"  {audience}: "
            f"mechanisms={len(model.get('mechanisms', []))}, "
            f"combination_rules="
            f"{len(model.get('combination_rules', []))}"
        )


if __name__ == "__main__":
    main()
