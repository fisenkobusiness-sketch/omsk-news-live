#!/usr/bin/env python3
"""
Read-only diagnostic tool for the Omsk News scoring pipeline.

Usage:
    python diagnostic.py
    python diagnostic.py editor_queue.json predictor_queue.json
    python diagnostic.py --top 30

The tool never modifies input files or GitHub. It diagnoses:
- hard exclusions (BPLA/drone/air-alert topics and promo posts)
- score distribution and saturation
- TOP-N score composition
- small-sample / cap warnings
- discrepancies between analysis and predictor scores
"""

from __future__ import annotations

import argparse
import sys
import json
import math
import re
import statistics

# Force UTF-8 for Windows/PyCharm console output.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
from pathlib import Path
from typing import Any


EXCLUDED_TOPIC_PATTERNS = [
    "бпла", "беспилотник", "беспилотники", "беспилотный",
    "беспилотные", "дрон", "дроны", "дрона", "дронами",
    "воздушная тревога", "воздушной тревоги", "ракетной опасности",
]

PROMO_PATTERNS = [
    "подписывайтесь", "подпишитесь", "подписывайся",
    "наши каналы", "самые свежие новости",
    "где публикуются самые свежие",
]


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def topic_text(t: dict) -> str:
    parts = [t.get("title"), t.get("text"), t.get("summary"), t.get("headline")]
    for m in t.get("members", []) or []:
        if isinstance(m, dict):
            parts.append(m.get("text"))
            parts.append(m.get("title"))
    return " ".join(norm(x) for x in parts if x)


def is_excluded(t: dict) -> bool:
    text = topic_text(t)
    return any(p in text for p in EXCLUDED_TOPIC_PATTERNS)


def is_promo(t: dict) -> bool:
    text = topic_text(t)
    return any(p in text for p in PROMO_PATTERNS)


def num(t: dict, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        v = t.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    return default


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def topics_from(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("topics", "items", "queue", "results", "data"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    k = (len(xs) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def aggregate_display_stats(t: dict) -> tuple[float, float, float, float]:
    """Read topic-level stats, falling back to member posts for diagnostics."""
    views = num(t, "views")
    likes = num(t, "likes")
    comments = num(t, "comments")
    reposts = num(t, "reposts")
    if any((likes, comments)) or not t.get("members"):
        return views, likes, comments, reposts
    mv = ml = mc = mr = 0.0
    for member in t.get("members", []) or []:
        if not isinstance(member, dict):
            continue
        post = member.get("post") if isinstance(member.get("post"), dict) else member
        mv += float(post.get("views", 0) or 0)
        ml += float(post.get("likes", 0) or 0)
        mc += float(post.get("comments", 0) or 0)
        mr += float(post.get("reposts", 0) or 0)
    return mv, ml, mc, mr

def metric(t: dict, key: str) -> float | None:
    value = t.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    pred = t.get("prediction")
    if isinstance(pred, dict) and isinstance(pred.get(key), (int, float)):
        return float(pred[key])
    return None


def label_score(s: float) -> str:
    if s >= 65:
        return "🟢 БРАТЬ"
    if s >= 50:
        return "🟡 ПРОВЕРИТЬ"
    if s >= 35:
        return "🔵 НАБЛЮДАТЬ"
    return "⚪ НИЗКИЙ"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("editor", nargs="?", default="runtime/editor_queue.json")
    ap.add_argument("predictor", nargs="?", default="runtime/predictor_queue.json")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    editor_path = Path(args.editor)
    predictor_path = Path(args.predictor)

    print("=" * 72)
    print("OMSK NEWS — DIAGNOSTIC (READ-ONLY)")
    print("=" * 72)

    if not editor_path.exists():
        print(f"ERROR: не найден {editor_path}")
        print("Укажите путь к editor_queue.json первым аргументом.")
        return
    if not predictor_path.exists():
        print(f"ERROR: не найден {predictor_path}")
        print("Укажите путь к predictor_queue.json вторым аргументом.")
        return

    editor_topics = topics_from(load_json(editor_path))
    predictor_topics = topics_from(load_json(predictor_path))

    print(f"Editor queue:    {len(editor_topics)} тем")
    print(f"Predictor queue: {len(predictor_topics)} тем")

    excluded = [t for t in editor_topics if is_excluded(t)]
    promo = [t for t in editor_topics if is_promo(t)]

    print("\n" + "-" * 72)
    print("HARD FILTER DIAGNOSTICS")
    print("-" * 72)
    print(f"БПЛА / дроны / тревога: {len(excluded)}")
    print(f"Промо / реклама:        {len(promo)}")

    if excluded:
        print("\nEXCLUDED TOPICS:")
        for t in excluded[:10]:
            print("  -", topic_text(t)[:180])
    if promo:
        print("\nPROMO TOPICS:")
        for t in promo[:10]:
            print("  -", topic_text(t)[:180])

    scores = []
    rows = []
    for t in predictor_topics:
        s = metric(t, "priority_score")
        if s is None:
            s = metric(t, "score")
        if s is None:
            continue
        scores.append(s)
        rows.append((s, t))

    rows.sort(key=lambda x: x[0], reverse=True)

    print("\n" + "-" * 72)
    print("SCORE DISTRIBUTION")
    print("-" * 72)
    if scores:
        print(f"mean:   {statistics.mean(scores):.1f}")
        print(f"median: {statistics.median(scores):.1f}")
        print(f"P90:    {percentile(scores, .90):.1f}")
        print(f"P95:    {percentile(scores, .95):.1f}")
        print(f"P99:    {percentile(scores, .99):.1f}")
        print(f"max:    {max(scores):.1f}")
        print(f">=90:   {sum(s >= 90 for s in scores)}")
        print(f">=95:   {sum(s >= 95 for s in scores)}")
        print(f">=99:   {sum(s >= 99 for s in scores)}")
        print(f"==100:  {sum(abs(s - 100) < 1e-9 for s in scores)}")

        saturation = sum(s >= 95 for s in scores) / len(scores)
        print(f"\nSaturation >=95: {saturation:.1%}")
        if saturation >= .10:
            print("⚠️ HIGH: слишком много тем упираются в верхнюю часть шкалы.")
        elif saturation >= .05:
            print("⚠️ MEDIUM: есть заметное насыщение.")
        else:
            print("OK: выраженного насыщения не видно.")

    print("\n" + "-" * 72)
    print(f"TOP {args.top} — SCORE BREAKDOWN")
    print("-" * 72)

    for i, (s, t) in enumerate(rows[:args.top], 1):
        title = t.get("title") or t.get("headline") or t.get("text") or ""
        title = re.sub(r"\s+", " ", str(title)).strip()
        pred = t.get("prediction") if isinstance(t.get("prediction"), dict) else {}

        views, likes, comments, reposts = aggregate_display_stats(t)
        posts = num(t, "posts")
        sources = num(t, "social_sources", "sources")

        viral = metric(t, "viral_score")
        editorial = metric(t, "editorial_score")
        confidence = metric(t, "confidence")

        print(f"\n#{i}  {s:.1f}  {label_score(s)}")
        print(f"    {title[:190]}")

        print(
            f"    views={views:.0f} likes={likes:.0f} "
            f"comments={comments:.0f} reposts={reposts:.0f} "
            f"posts={posts:.0f} sources={sources:.0f}"
        )
        if viral is not None or editorial is not None or confidence is not None:
            print(
                f"    viral={viral if viral is not None else '-'} "
                f"editorial={editorial if editorial is not None else '-'} "
                f"confidence={confidence if confidence is not None else '-'}"
            )

        warnings = []
        if is_excluded(t):
            warnings.append("EXCLUDED_TOPIC")
        if is_promo(t):
            warnings.append("PROMO")
        if views < 500:
            warnings.append("LOW_VIEWS")
        if views < 1000 and comments >= 5:
            warnings.append("SMALL_SAMPLE")
        if s >= 99:
            warnings.append("SCORE_NEAR_CAP")

        # These are diagnostics of the current formulas, not replacement scores.
        if views > 0:
            engagement = ((likes + comments * 2 + reposts * 4) / views) * 1000
            discussion = (comments / views) * 2500
            spread = (reposts / views) * 5000
            if engagement >= 100:
                warnings.append("ENGAGEMENT_CAP")
            if discussion >= 100:
                warnings.append("DISCUSSION_CAP")
            if spread >= 100:
                warnings.append("SPREAD_CAP")

        if warnings:
            print("    ⚠️ " + ", ".join(warnings))

    # Cross-check: editor score vs predictor score.
    pairs = []
    for t in predictor_topics:
        p = metric(t, "priority_score")
        e = metric(t, "score")
        if p is not None and e is not None:
            pairs.append((p, e, t))
    if pairs:
        mismatches = sorted(pairs, key=lambda x: x[0] - x[1], reverse=True)
        print("\n" + "-" * 72)
        print("EDITOR vs PREDICTOR")
        print("-" * 72)
        print(f"Тем с обоими score: {len(pairs)}")
        print("Наибольший разрыв:")
        for p, e, t in mismatches[:5]:
            title = str(t.get("title") or t.get("headline") or t.get("text") or "")
            print(f"  predictor={p:.1f} editor={e:.1f} Δ={p-e:+.1f} | {title[:120]}")

    print("\n" + "=" * 72)
    print("DIAGNOSTIC COMPLETE — input files were not modified.")
    print("=" * 72)


if __name__ == "__main__":
    main()
