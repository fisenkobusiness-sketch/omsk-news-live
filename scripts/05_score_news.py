# -*- coding: utf-8 -*-
"""05. Оценка свежих новостей обеими моделями + Audience Separator."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    AUDIENCE_PROFILES,
    AUDIENCES,
    EDITORIAL_MODEL,
    PRIORITY_THRESHOLD,
    RESERVE_THRESHOLD,
    SCORING_INPUT,
    SCORING_OUTPUT,
    TAKE_THRESHOLD,
)
from lib.analytics_core import score_fresh_post, classify_one
from lib.audience_router import (
    route_scores,
    score_audience_affinity,
    affinity_route,
    extract_event_meta,
)


def load_json(path):
    with path.open(
        "r",
        encoding="utf-8",
    ) as handle:
        return json.load(handle)


def save_json(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def assign_status(score):
    score = float(score)

    if score >= PRIORITY_THRESHOLD:
        return "ПРИОРИТЕТ"

    if score >= TAKE_THRESHOLD:
        return "ВЗЯТЬ"

    if score >= RESERVE_THRESHOLD:
        return "РЕЗЕРВ"

    return "ПРОПУСК"


def main():
    bundle = load_json(
        EDITORIAL_MODEL
    )

    models = bundle.get(
        "models",
        {},
    )

    missing = [
        audience
        for audience in AUDIENCES
        if audience not in models
    ]

    if missing:
        raise RuntimeError(
            "В editorial_model.json отсутствуют "
            f"модели: {missing}"
        )

    profile_bundle = load_json(
        AUDIENCE_PROFILES
    )

    profiles = profile_bundle.get(
        "audiences",
        {},
    )

    affinity_model = profile_bundle.get("audience_affinity_model", {})

    missing = [
        audience
        for audience in AUDIENCES
        if audience not in profiles
    ]

    if missing:
        raise RuntimeError(
            "В audience_profiles.json отсутствуют "
            f"профили: {missing}"
        )

    fresh = load_json(
        SCORING_INPUT
    )

    if isinstance(fresh, list):
        posts = fresh
    elif isinstance(fresh, dict):
        posts = fresh.get(
            "posts",
            [fresh],
        )
    else:
        posts = []

    if not posts:
        raise RuntimeError(
            f"fresh_news.json пуст: {SCORING_INPUT}"
        )

    results = []

    for post in posts:
        audience_payload = {}
        raw_scores = {}

        for audience in AUDIENCES:
            scored = score_fresh_post(
                post,
                models[audience],
            )

            scored = dict(scored)

            editorial_score = float(
                scored.get(
                    "potential_score",
                    0.0,
                )
            )

            scored[
                "editorial_score_absolute"
            ] = round(
                editorial_score,
                2,
            )

            scored[
                "editorial_status"
            ] = assign_status(
                editorial_score
            )

            audience_payload[
                audience
            ] = scored

            raw_scores[
                audience
            ] = editorial_score

        mechanisms = audience_payload[
            AUDIENCES[0]
        ].get(
            "mechanisms_used",
            [],
        )

        # Build the same affinity prior that chronological OOS uses.
        affinity_post = dict(post)
        try:
            affinity_classified = classify_one(affinity_post)
            if isinstance(affinity_classified, dict):
                affinity_post.update(affinity_classified)
        except Exception:
            pass
        affinity_post["mechanisms"] = mechanisms
        affinity_post["mechanism_strength"] = audience_payload[AUDIENCES[0]].get("mechanism_strength")
        affinity_post["content_type"] = audience_payload[AUDIENCES[0]].get("content_type") or affinity_post.get("content_type")

        affinity = score_audience_affinity(
            affinity_post,
            affinity_model,
        )
        affinity_decision = affinity_route(affinity)

        # v2.4: one shared event-metadata extractor for fresh and OOS.
        # This fixes «погибли три человека» being reduced to one lexical hit.
        scored_reference = audience_payload[AUDIENCES[0]]
        event_meta = extract_event_meta(post, scored_reference)
        event_strength = float(event_meta.get("event_strength", 0.0) or 0.0)

        routing = route_scores(
            raw_scores,
            profiles,
            mechanisms,
            affinity=affinity,
            event_strength=event_strength,
            event_meta=event_meta,
        )

        result = dict(post)

        result["audience_scores"] = audience_payload
        result["audience_fit"] = routing["fits"]
        result["audience_percentile"] = routing.get("percentiles", {})
        result["audience_mechanism_fit"] = routing["mechanism_fits"]
        result["audience_calibration"] = routing.get("calibration", {})
        result["audience_affinity"] = affinity
        result["audience_affinity_diagnostic_routing"] = affinity_decision

        result["audience_routing"] = {
            "decision": routing.get("decision"),
            "best_audience": routing.get("best_audience"),
            "second_audience": routing.get("second_audience"),
            "fit_margin": routing.get("fit_margin"),
            "event_strength": routing.get("event_strength", event_strength),
            "event_dominant": routing.get("event_dominant", False),
            "event_dominance": routing.get("event_dominance", {}),
            "method": routing.get("method", "calibrated_performance_60_affinity_prior_40"),
            "weights": routing.get("weights", {"performance": 0.60, "affinity": 0.40}),
            "affinity_diagnostic": affinity_decision,
            "status": "DIAGNOSTIC_ONLY",
        }

        # Старые поля оставляем для совместимости.
        result[
            "editorial_score_absolute"
        ] = round(
            max(raw_scores.values()),
            2,
        )

        result[
            "fresh_rank_score"
        ] = result[
            "editorial_score_absolute"
        ]

        result[
            "editorial_status"
        ] = assign_status(
            result[
                "editorial_score_absolute"
            ]
        )

        results.append(result)

    results.sort(
        key=lambda row: max(
            row.get(
                "audience_fit",
                {}
            ).values()
            or [0]
        ),
        reverse=True,
    )

    for rank, row in enumerate(
        results,
        start=1,
    ):
        row[
            "editorial_rank"
        ] = rank

    save_json(
        SCORING_OUTPUT,
        results,
    )

    print(
        f"Сохранено: {SCORING_OUTPUT}"
    )
    print(
        "ВАЖНО: audience_routing.status="
        "DIAGNOSTIC_ONLY"
    )
    print(
        "Raw score между аудиториями "
        "не используется для выбора паблика."
    )

    for row in results[:20]:
        routing = row[
            "audience_routing"
        ]

        title = str(
            row.get("title")
            or row.get("text")
            or ""
        ).replace(
            "\n",
            " ",
        )[:90]

        print(
            f"{title} | "
            f"fit={row.get('audience_fit')} | "
            f"{routing.get('decision')} | "
            f"margin={routing.get('fit_margin')}"
        )


if __name__ == "__main__":
    main()
