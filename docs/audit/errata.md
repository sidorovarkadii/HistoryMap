# Milestone 1 audit — errata (2026-09-28)

> The audit record (`feasibility.md`, `metrics.md`, `stage1-projection.md`) is left as it was produced. This file
> corrects conclusions that should not guide implementation. Raised by review 3; figures re-checked against the
> cached entity JSON (read-only) on 2026-09-28.

| # | Audit statement | Correction |
|---|---|---|
| E1 | "97% of life events have no relationship" | True only **among the audited properties** (P361, P155/P156, P710, P50/P170, P61, P793, P1344). Counting parent/child/spouse (P22/P25/P40/P26), office (P39), dynasty (P53), noble title (P97), religious order (P611), notable work (P800) and conflict (P607), life events with no outgoing relationship fall from **1,048/1,077 to 205/1,077 (≈ 19%)**. These are candidate connections — not yet verified or relevant to any story |
| E2 | Life figures mix people and events | **774 distinct people** underlie the 1,077 retained life events (sample). People and life events must be counted separately |
| E3 | "Map-ready" used as if it meant eligible | Map-readiness is a **presentation** check. Historical inclusion is decided separately (v1.0 §7–§8) |
| E4 | Proposed Stage 1 total "≈ 250–300 events" | Understated: with 77 architecture events the listed rows sum to **316–336**; with the alternative 40, to **279–299** — before cross-category deduplication |
| E5 | "Empty coverage cells are genuine data gaps" | Not established. Empty cells may reflect discovery rules (type lists, direct-P31), sampling, or exclusion policies |
| E6 | Shared location suggested as a source of architecture/culture links | A shared location is **contextual evidence only**, not a default substitute for a relationship |
| E7 | "Church building" (Q16970) read as the parish-church bulk | The count (1,350 of 2,832 retained architecture entities) measures **discovery volume**; the direct type does not establish that a building is an ordinary parish church |
| E8 | Architecture relationships "88% none" | Also among audited properties only: **259 of 2,832** retained buildings have a founder (P112), commissioner (P88) or architect (P84) claim, not counted by the audit |
| E9 | Office jurisdiction via qualifier "of" (P642) | P642 no longer returns a label/description from Wikidata (appears deleted); jurisdiction comes from the office item's P1001 |

The verdicts per category (war go; life/architecture/religion adjust; culture curate) are superseded by the
connection-led selection model in `docs/architecture.md` v1.0-draft.
