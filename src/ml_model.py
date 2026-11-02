"""Small, dependency-free engagement model trained from tracker checkpoints."""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "runtime" / "smm_poiskovik_engagement.sqlite3"
MODEL_PATH = ROOT / "runtime" / "engagement_model.json"
MODEL_PATH_1H = ROOT / "runtime" / "engagement_model_1h.json"
TEXT_GROUPS = {
    "incident": ("авари", "дтп", "пожар", "взрыв", "погиб", "пострад", "спасател"),
    "crime": ("полици", "суд", "следств", "подозрева", "арест", "мошен", "украл", "штраф"),
    "transport": ("дорог", "маршрут", "автобус", "трамва", "перекрест", "движени", "мост"),
    "weather": ("погод", "снег", "дожд", "мороз", "тепл", "ветер", "гололед"),
    "city_services": ("ремонт", "отключ", "вода", "отоплен", "благоустрой", "мусор", "коммунал"),
    "public_decision": ("мэр", "губернатор", "власти", "решили", "закон", "тариф", "запрет"),
    "sports": ("авангард", "хоккей", "матч", "спорт", "гол", "игрок"),
    "culture": ("театр", "концерт", "выставк", "фестиваль", "музей", "памятник"),
}
FEATURES = ("text_length", "hour_sin", "hour_cos") + tuple(f"topic_{key}" for key in TEXT_GROUPS)


def _semantic_features(text):
    normalized = str(text or "").lower().replace("ё", "е")
    return [float(any(word in normalized for word in words)) for words in TEXT_GROUPS.values()]


def _model_path(horizon, audience=None):
    if audience:
        return ROOT / "runtime" / f"engagement_model_{audience}_{horizon}h.json"
    return MODEL_PATH_1H if horizon == 1 else MODEL_PATH


def _features(row):
    members = json.loads(row["member_posts_json"] or "[]")
    posts = [m.get("post", m) if isinstance(m, dict) else {} for m in members]
    text = " ".join(str(p.get("text") or "") for p in posts)
    ts = max((int(p.get("timestamp") or 0) for p in posts), default=0)
    hour = (ts // 3600) % 24
    vals = [min(len(text), 2000) / 2000, math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24)]
    vals += _semantic_features(text)
    return [1.0] + [float(v or 0) for v in vals]


def features_for_topic(topic):
    members = topic.get("members") or []
    posts = [m.get("post", m) if isinstance(m, dict) else {} for m in members]
    text = " ".join(str(p.get("text") or "") for p in posts) or str(topic.get("text") or "")
    timestamp = max((int(p.get("timestamp") or 0) for p in posts), default=0)
    hour = (timestamp // 3600) % 24
    values = [min(len(text), 2000) / 2000,
            math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24)]
    return values + _semantic_features(text)


def _solve(matrix, vector):
    n = len(vector)
    a = [list(map(float, matrix[i])) + [float(vector[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            continue
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [x / scale for x in a[col]]
        for r in range(n):
            if r != col:
                factor = a[r][col]
                a[r] = [x - factor * y for x, y in zip(a[r], a[col])]
    return [a[i][-1] for i in range(n)]


def _fit(xs, ys):
    d = len(xs[0])
    gram = [[sum(x[i] * x[j] for x in xs) for j in range(d)] for i in range(d)]
    for i in range(1, d):
        gram[i][i] += 0.1
    rhs = [sum(x[i] * y for x, y in zip(xs, ys)) for i in range(d)]
    return _solve(gram, rhs)


def _rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    for rank, index in enumerate(order):
        ranks[index] = float(rank)
    return ranks


def _spearman(a, b):
    if len(a) < 2:
        return None
    ra, rb = _rank(a), _rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra); db = sum((y - mb) ** 2 for y in rb)
    return cov / math.sqrt(da * db) if da and db else None


def evaluate(db_path: Path = DB_PATH, horizon: int = 3, test_fraction: float = 0.2, paired: bool = True):
    """Chronological holdout evaluation; does not write to the database or model file."""
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        other = 3 if horizon == 1 else 1
        paired_clause = f" AND completed_{other}h=1 AND score_at_{other}h IS NOT NULL" if paired else ""
        rows = db.execute(f"SELECT * FROM observations WHERE completed_{horizon}h=1 AND score_at_{horizon}h IS NOT NULL{paired_clause} ORDER BY predicted_at,observation_id").fetchall()
    n = len(rows); split = max(1, min(n - 1, int(n * (1.0 - test_fraction))))
    if n < 30:
        return {"samples": n, "reason": "need_30_completed_samples"}
    train_rows, test_rows = rows[:split], rows[split:]
    xs_train = [_features(row) for row in train_rows]
    ys_train = [math.log1p(max(0.0, float(row[f"score_at_{horizon}h"]))) for row in train_rows]
    coefficients = _fit(xs_train, ys_train)
    xs_test = [_features(row) for row in test_rows]
    ys_test = [math.log1p(max(0.0, float(row[f"score_at_{horizon}h"]))) for row in test_rows]
    preds = [sum(c * x for c, x in zip(coefficients, row)) for row in xs_test]
    median = sorted(ys_train)[len(ys_train) // 2]
    mae_ml = sum(abs(y - p) for y, p in zip(ys_test, preds)) / len(ys_test)
    mae_baseline = sum(abs(y - median) for y in ys_test) / len(ys_test)
    baseline_scores = [float(row["score"] or 0) for row in test_rows]
    result = {
        "horizon_hours": horizon, "train_samples": len(train_rows), "test_samples": len(test_rows),
        "test_first_timestamp": int(test_rows[0]["predicted_at"]),
        "test_last_timestamp": int(test_rows[-1]["predicted_at"]),
        "mae_log_engagement_ml": round(mae_ml, 6),
        "mae_log_engagement_train_median": round(mae_baseline, 6),
        "mae_improvement_percent": round(100 * (mae_baseline - mae_ml) / mae_baseline, 2) if mae_baseline else None,
        "spearman_ml": round(_spearman(preds, ys_test), 4) if _spearman(preds, ys_test) is not None else None,
        "spearman_current_heuristic": round(_spearman(baseline_scores, ys_test), 4) if _spearman(baseline_scores, ys_test) is not None else None,
    }
    by_audience = {}
    for audience in sorted({row["audience"] for row in test_rows}):
        indices = [i for i, row in enumerate(test_rows) if row["audience"] == audience]
        by_audience[audience] = {
            "test_samples": len(indices),
            "spearman_ml": round(_spearman([preds[i] for i in indices], [ys_test[i] for i in indices]), 4) if len(indices) >= 2 else None,
            "spearman_current_heuristic": round(_spearman([baseline_scores[i] for i in indices], [ys_test[i] for i in indices]), 4) if len(indices) >= 2 else None,
        }
    result["by_audience"] = by_audience
    return result


def train(db_path: Path = DB_PATH, model_path: Path | None = None, horizon: int = 3, audience: str | None = None):
    """Train ridge regression on completed checkpoints; persist coefficients atomically."""
    model_path = model_path or _model_path(horizon, audience)
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        where_audience = " AND audience=?" if audience else ""
        params = (audience,) if audience else ()
        rows = db.execute(f"SELECT * FROM observations WHERE completed_{horizon}h=1 AND score_at_{horizon}h IS NOT NULL{where_audience} ORDER BY predicted_at", params).fetchall()
    if len(rows) < 30:
        return {"trained": False, "samples": len(rows), "reason": "need_30_completed_samples"}
    try:
        current = json.loads(model_path.read_text(encoding="utf-8"))
        if current.get("samples") == len(rows) and current.get("horizon_hours") == horizon and current.get("audience") == audience and current.get("features") == list(FEATURES):
            return {"trained": False, "samples": len(rows), "reason": "up_to_date"}
    except (OSError, ValueError, TypeError):
        pass
    xs = [_features(row) for row in rows]
    ys = [math.log1p(max(0.0, float(row[f"score_at_{horizon}h"]))) for row in rows]
    coefficients = _fit(xs, ys)
    sorted_y = sorted(ys)
    scale = math.expm1(sorted_y[min(len(sorted_y) - 1, int(0.9 * len(sorted_y)))])
    payload = {"version": 1, "horizon_hours": horizon, "audience": audience, "samples": len(rows), "features": list(FEATURES), "coefficients": coefficients, "score_scale": max(scale, 1e-6)}
    model_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = model_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(model_path)
    return {"trained": True, "samples": len(rows), "model_path": str(model_path)}


def predict(features: list[float], model_path: Path | None = None, horizon: int = 3, audience: str | None = None):
    model_path = model_path or _model_path(horizon, audience)
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
        if model.get("features") != list(FEATURES):
            return None, 0, 1.0
        coeff = model["coefficients"]
        value = math.expm1(sum(c * x for c, x in zip(coeff, [1.0] + features)))
        return max(0.0, value), int(model["samples"]), float(model.get("score_scale", 1.0))
    except (OSError, ValueError, KeyError, TypeError):
        return None, 0, 1.0
