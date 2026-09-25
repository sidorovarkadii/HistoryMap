# Stage 1 projections (generated)

> `pipeline/audit/stage1_projection.py`. *Map-ready* = retained, located in bbox, precision year or finer, status ok. Counts extrapolated to the full candidate set where the category was sampled.

## Map-ready events by prominence threshold (sitelinks ≥ T)

| category | all retained | map-ready | T≥5 | T≥10 | T≥20 | T≥40 |
|---|---|---|---|---|---|---|
| war | 508 | 465 | 197 | 104 | 34 | 10 |
| life | 8048 | 3385 | 2376 | 1831 | 1039 | 374 |
| architecture | 2956 | 998 | 341 | 183 | 77 | 22 |
| culture | 533 | 19 | 4 | 1 | 0 | 0 |
| religion | 41 | 38 | 8 | 4 | 3 | 2 |

## Century pulse — events that would reveal at the same instant

Events dated coarser than a year reveal at their interval midpoint (§4.3). Largest same-year clusters among retained, located events:

| category | coarser than year (located) | top same-year clusters |
|---|---|---|
| war | 5 | 951: 2, 1015: 1, 985: 1 |
| life | 785 | 1051: 411, 951: 194, 1501: 60 |
| architecture | 1837 | 1051: 1284, 951: 421, 1101: 17 |
| culture | 276 | 1149: 79, 951: 26, 1100: 24 |
| religion | 0 |  |

## Life ↔ war connectivity (via P710 participant — the `eventsInvolving` index)

- War events naming a sampled person as participant: 2 of 508 (≈ 15 if all 22418 people were fetched)
- Distinct sampled people involved: 2 (≈ 15 extrapolated)
- Life events have almost no outgoing links (97% none); their connections come from **reverse** participant links and `sameSubject` (birth↔death), exactly the v0.4 §6 indexes.
