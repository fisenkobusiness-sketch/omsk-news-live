# Editorial ranking model (v1 design)

## Goal
Produce one comparable priority score for every eligible Omsk story. The score ranks editorial attention; it is not a probability of virality and not a fact-confidence score.

## Current pipeline findings
- `src/analysis.py` calculates `viral_score`, `editorial_score`, and `score`. These overlap: editorial_score includes viral_score, and score then blends both again with freshness.
- `src/predictor.py` combines viral_score and editorial_score again, plus audience counters and freshness. This double-counts overlapping signals and makes the meaning of the final score unclear.
- `confidence` is used as verification metadata in predictor, but it is also embedded in editorial_score upstream.
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
5. Verification confidence is reported separately. High-risk stories that require verification are excluded from the active work queue until their evidence is adequate; they do not receive a separate holding status.
6. Cross-posts from the same source do not count as independent confirmation.
7. One canonical sorted queue uses descending `priority_score`. Rubrics are labels applied after ranking, never separate score systems.

## Validation before production
- Unit tests for each feature and hard exclusion.
- Invariant: eligible queue is sorted descending by `priority_score`.
- Invariant: changing only confidence changes verification metadata, not audience-interest features.
- Invariant: absent counters are exposed as missing/low-coverage, not confused with measured zero engagement.
- Regression fixtures: high-impact low-engagement story, ordinary administrative update, fast-growing complaint, stale story, excluded topic, and nonlocal story.
- Compare the old and new rankings on a saved pool; inspect large rank changes before replacing production output.

## Editorial queue statuses

The pipeline uses only two editorial statuses:
- `take_now` — priority score is at least 45, or the topic is a qualifying viral complaint/signal; the story enters editorial work. Viral complaints must be written as attributed reports, not established facts.
- `reject` — score is below 45, the topic is excluded by editorial rules, or a high-risk story is blocked by the predictor's verification gate. The technical `editorial_exclusion_reason` distinguishes low priority from required verification.

Do not emit `check` or `watch` statuses. Verification remains a separate safety gate, not a third editorial status.

## Migration policy
Do not manually edit `editorial_pool.json`. Keep the current output until the new model passes tests and a side-by-side ranking comparison. Remove legacy score fields only in a later version after all consumers are migrated.
