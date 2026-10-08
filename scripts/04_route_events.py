# -*- coding: utf-8 -*-
"""Diagnostic Audience Router for event-level NewsEvents.

Consumes the discovery/event layer only. Historical dataset and 05_score_news.py
are intentionally untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import AUDIENCES, AUDIENCE_PROFILES, EDITORIAL_MODEL
from lib.analytics_core import prepare_fresh_classification, score_fresh_post
from lib.audience_router import extract_event_meta, route_scores, score_audience_affinity

EVENTS_INPUT = ROOT / "data" / "events" / "news_events.jsonl"
EVENTS_OUTPUT = ROOT / "data" / "events" / "routed_news_events.jsonl"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def event_to_post(event):
    """Convert a NewsEvent representative into the flat post shape expected
    by analytics_core and audience_router.
    """
    representative = dict(event.get("representative_post") or {})
    nested_post = dict(representative.get("post") or {})

    # analytics_core reads title/text and other post fields from the top level.
    # NewsEvent stores the original SourcePost under representative_post["post"],
    # so flatten that nested object before classification/scoring.
    post = dict(nested_post)
    for key, value in representative.items():
        if key != "post" and key not in post:
            post[key] = value

    post["text"] = event.get("canonical_text") or post.get("text") or ""
    post.setdefault("title", post["text"][:180])
    return post


def main():
    if not EVENTS_INPUT.exists():
        raise FileNotFoundError(
            f"Не найден {EVENTS_INPUT}. Сначала: python scripts/02_build_events.py"
        )

    model_bundle = load_json(EDITORIAL_MODEL)
    models = model_bundle.get("models", {})
    profile_bundle = load_json(AUDIENCE_PROFILES)
    profiles = profile_bundle.get("audiences", {})
    affinity_model = profile_bundle.get("audience_affinity_model", {})

    missing_models = [a for a in AUDIENCES if a not in models]
    missing_profiles = [a for a in AUDIENCES if a not in profiles]
    if missing_models or missing_profiles:
        raise RuntimeError(
            f"Не хватает моделей/профилей: models={missing_models}, profiles={missing_profiles}"
        )

    events = read_jsonl(EVENTS_INPUT)
    routed = []

    for event in events:
        post = event_to_post(event)
        classification = prepare_fresh_classification(post)
        audience_payload = {}
        raw_scores = {}

        for audience in AUDIENCES:
            scored = score_fresh_post(
                post,
                models[audience],
                classification=classification,
            )
            score = float(scored.get("potential_score", 0.0) or 0.0)
            audience_payload[audience] = {
                "editorial_score_absolute": round(score, 2),
                "content_type": scored.get("content_type"),
                "mechanisms": scored.get("mechanisms_used", []),
                "mechanism_strength": scored.get("mechanism_strength"),
                "fresh_event_strength": scored.get("fresh_event_strength"),
            }
            raw_scores[audience] = score

        primary = audience_payload[AUDIENCES[0]]
        affinity_post = dict(post)
        affinity_post["mechanisms"] = primary.get("mechanisms", [])
        affinity_post["mechanisms_used"] = primary.get("mechanisms", [])
        affinity_post["mechanism_strength"] = primary.get("mechanism_strength")
        affinity_post["content_type"] = primary.get("content_type")

        affinity = score_audience_affinity(affinity_post, affinity_model)

        # Reuse scored classification/fresh-event strength so event-level
        # routing stays aligned with analytics_core.
        reference_scored = {
            "classification": classification,
            "fresh_event_strength": primary.get("fresh_event_strength", 0.0),
            "mechanism_strength": primary.get("mechanism_strength"),
            "content_type": primary.get("content_type"),
        }
        event_meta = extract_event_meta(post, reference_scored)
        routing = route_scores(
            raw_scores,
            profiles,
            primary.get("mechanisms", []),
            affinity=affinity,
            event_strength=float(event_meta.get("event_strength", 0.0) or 0.0),
            event_meta=event_meta,
        )

        row = dict(event)
        row["audience_scores"] = audience_payload
        row["audience_affinity"] = affinity
        row["audience_routing"] = {
            "recommended_target": routing.get("best_audience"),
            "secondary_candidate": routing.get("second_audience"),
            "confidence": routing.get("fit_margin"),
            "decision": routing.get("decision"),
            "fit": routing.get("fits", {}),
            "expected_potential": routing.get("expected_potential", {}),
            "percentiles": routing.get("percentiles", {}),
            "event_strength": routing.get("event_strength", 0.0),
            "event_fit": routing.get("event_fit", {}),
            "event_dominant": routing.get("event_dominant", False),
            "method": routing.get("method"),
            "status": "DIAGNOSTIC_ONLY",
        }
        routed.append(row)

    routed.sort(
        key=lambda event: max(
            (event.get("audience_routing", {}).get("fit") or {}).values() or [0.0]
        ),
        reverse=True,
    )

    for rank, event in enumerate(routed, start=1):
        event["editorial_rank"] = rank

    write_jsonl(EVENTS_OUTPUT, routed)

    print(f"NewsEvent: {len(routed)}")
    print(f"Сохранено: {EVENTS_OUTPUT}")
    print("Audience Router: DIAGNOSTIC_ONLY")
    for event in routed[:20]:
        routing = event.get("audience_routing", {})
        scores = event.get("audience_scores", {})
        print(
            f"{event.get('event_id')} | {event.get('event_type')} | "
            f"target={routing.get('recommended_target')} | "
            f"secondary={routing.get('secondary_candidate')} | "
            f"confidence={routing.get('confidence')} | "
            f"decision={routing.get('decision')} | "
            f"freshness={event.get('freshness_age_minutes')}m | "
            f"spread={event.get('spread_minutes')}m"
        )
        print(
            f"  scores: golos={scores.get('golos', {}).get('editorial_score_absolute')} "
            f"zhest={scores.get('zhest', {}).get('editorial_score_absolute')} | "
            f"mechanisms={scores.get('golos', {}).get('mechanisms')} | "
            f"strength={scores.get('golos', {}).get('mechanism_strength')} | "
            f"fresh_event_strength={scores.get('golos', {}).get('fresh_event_strength')} | "
            f"event_fit={routing.get('event_fit')} | "
            f"fits={routing.get('fit')} | affinity={event.get('audience_affinity')}"
        )


if __name__ == "__main__":
    main()
