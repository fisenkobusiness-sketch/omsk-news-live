# Editorial ranking model (v1 design)

## Goal
Produce one comparable priority score for every eligible Omsk story. The score ranks editorial attention; it is not a probability of virality and not a fact-confidence score.

## Current pipeline findings
- `src/analysis.py` calculates `viral_score`, `editorial_score`, and `score`. These overlap: editorial_score includes viral_score, and score then blends both again with freshness.
- `src/predictor.py` combines viral_score and editorial_score again, plus audience counters and freshness. This double-counts overlapping signals and makes the meaning of the final score unclear.
- `confidence` is verification metadata only; it must not be embedded in `editorial_score` or affect the canonical ranking.
- The pipeline has no explicit, shared event-impact representation. Predictor uses a short list of text substrings, so important stories can be missed and irrelevant word matches can be rewarded.
- The analyzer's output and predictor's output have distinct sort keys. Only the final queue should define the displayed ranking.

## Canonical contract
Each topic must keep raw evidence separate from derived features:
- Evidence: source posts, timestamps, URLs, views, likes, comments, reposts, source identities.
- Classification: content type, local relevance, event class/impact, attribution/evidence status, exclusion reason.
- Independent features, each normalized to 0–100: freshness, audience engagement, discussion, reshare rate, reach, velocity, local usefulness, event impact, evidence quality.
- Final `priority_score`: one 0–100 editorial triage score calculated only from the independent features.
- `viral_score` and analyzer `score` remain legacy/diagnostic fields during migration; they must not be presented as the canonical final ranking.
- `confidence` means evidence/verification confidence only. It must not be described as popularity.
- Missing metrics must be marked as missing, not silently interpreted as evidence of low audience interest. Where the data is missing, score only observed dimensions and expose coverage.

## Ranking principles
1. Hard exclusions are eligibility rules, not negative popularity points.
2. Freshness is time-decayed and timezone-aware (Asia/Omsk); stale/missing timestamps are rejected by the existing same-day gate.
3. Audience response, reach and spread are distinct features; raw counts must be normalized so one large account cannot dominate the entire ranking.
4. Local usefulness and event impact are explicit editorial dimensions, not hidden bonuses buried in text matching.
5. Verification confidence and source attribution are notes, not ranking bonuses. Do not wait for official confirmation before detecting or ranking a fresh story. Preserve attribution (for example, “according to eyewitnesses” or “the local channel reports”) and do not present unverified details as established facts. Hard editorial exclusions still apply.
6. Cross-posts from the same source do not count as independent confirmation.
7. One canonical sorted queue uses descending `priority_score`. Rubrics are labels applied after ranking, never separate score systems.

## Validation before production
- Unit tests for each feature and hard exclusion.
- Invariant: eligible queue is sorted descending by `priority_score`.
- Invariant: changing only confidence or official attribution changes notes/metadata, not the editorial priority score.
- Invariant: absent counters are exposed as missing/low-coverage, not confused with measured zero engagement.
- Regression fixtures: high-impact low-engagement story, ordinary administrative update, fast-growing complaint, stale story, excluded topic, and nonlocal story.
- Compare the old and new rankings on a saved pool; inspect large rank changes before replacing production output.

## Editorial queue statuses

The pipeline uses only two editorial statuses:
- `take_now` — priority score is at least 45, or the topic is a qualifying viral complaint/signal; the story enters editorial work. A story need not have official confirmation to qualify. Viral complaints and eyewitness reports must be written with clear attribution, not as established facts.
- `reject` — score is below 45 or the topic is excluded by editorial rules. There is no general official-confirmation gate; hard exclusions and the prohibition on presenting serious unverified accusations as facts still apply.

Do not emit `check` or `watch` statuses. Attribution is kept as context; official confirmation is not a third status or a prerequisite for early selection.

## Migration policy
Do not manually edit `editorial_pool.json`. Keep the current output until the new model passes tests and a side-by-side ranking comparison. Remove legacy score fields only in a later version after all consumers are migrated.
