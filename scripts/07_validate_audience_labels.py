# -*- coding: utf-8 -*-
"""Validate current routing against the editor-supplied gold labels."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCORING=ROOT/"data/scoring/scored_news.json"
GOLD=ROOT/"data/scoring/audience_gold_seed.json"
def bucket(decision):
    d=str(decision or "")
    if d == "BOTH": return "both"
    if d == "SKIP_OR_EDITORIAL_REVIEW": return "skip"
    if d.startswith("golos_") or d == "golos": return "golos"
    if d.startswith("zhest_") or d == "zhest": return "zhest"
    return "unknown"
rows=json.loads(SCORING.read_text(encoding="utf-8"))
gold=json.loads(GOLD.read_text(encoding="utf-8"))["labels"]
by_id={x.get("id"):x for x in rows}
correct=0
for i,item in enumerate(gold,1):
    row=by_id.get(item.get("id"),{})
    pred=bucket(row.get("audience_routing",{}).get("decision"))
    exp=item.get("label")
    ok=pred==exp
    correct += int(ok)
    print(f"{i:02d}. {'OK' if ok else 'MISS'} | {exp:5s} | {pred:5s} | {item.get('title','')[:90]}")
acc=correct/max(1,len(gold))
print(f"Manual editorial calibration: {correct}/{len(gold)} = {acc*100:.1f}%")
out=ROOT/"data/scoring/audience_gold_validation.json"
out.write_text(json.dumps({"correct":correct,"total":len(gold),"accuracy":round(acc,4)},ensure_ascii=False,indent=2),encoding="utf-8")
print(f"Report: {out}")
