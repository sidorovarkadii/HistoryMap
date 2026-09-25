# Milestone 1 — Data feasibility audit (Stage 1, 901–1099 CE)

> **Status:** complete, for your review. Audit run 2026-09-24/25 against live Wikidata.
> **Generated evidence:** [`metrics.md`](metrics.md) (all metrics), [`stage1-projection.md`](stage1-projection.md)
> (dataset sizing), `sample-<category>.csv` (stratified + hard-case rows to spot-check by hand).
> **Reproduce:** `python pipeline/audit/sample.py` → `measure.py` → `stage1_projection.py`
> (a re-run is served entirely from cache: verified **0 HTTP requests**).

## 1. Verdict per category

| Category | Verdict | Why, in one line |
|---|---|---|
| **War** | ✅ **Go** (automatic import) | 508 events in the window; 94% located; dates mostly day or year precision; 60% belong to a war (P361); 1% conflicting dates |
| **Life** | 🟡 **Adjust** | Huge (~8,000 events) and 97% without their own links. Select people **by connection** (P607 → window wars, sequences) plus a prominence threshold, not by prominence alone |
| **Architecture** | 🟡 **Adjust** | Plenty (~3,000), but 62% dated only to a century and 88% unconnected. Use it as a *context layer*: year-precision and prominent buildings on the map, the rest in the list |
| **Science & culture** | 🔴 **Curate** (no automatic import in Stage 1) | 78% have no creation place; what remains is mostly museum-catalogue fragments. Famous works are unlocated (Bayeux Tapestry) or missing entirely (Canon of Medicine, Book of Optics, Beowulf) |
| **Religion** | 🟡 **Adjust** (import + curated seeds) | Councils and synods import well (41 events), but the defining events are excluded or mistyped: **East–West Schism excluded** (no place data); Investiture Controversy, Christianization of Rus', Peace of God and Cluniac reform sit outside the religious types |

All five categories stay in Stage 1, as agreed. What changes is **how** each one is sourced.

## 2. What the data looks like

| Category | Retained (≈ full) | Map-ready¹ | …with sitelinks ≥10 | ≥20 | Coarser than year | Conflicting claims | No relationships |
|---|---|---|---|---|---|---|---|
| War | 508 | 465 | 104 | 34 | 2% | 6 (1%) | 19% |
| Life | ≈ 8,048 | ≈ 3,385 | ≈ 1,831 | ≈ 1,039 | 29% | 57 in sample (≈ 5%) | 97% |
| Architecture | ≈ 2,956 | ≈ 998 | ≈ 183 | ≈ 77 | 64% | 115 (4%) | 88% |
| Culture | ≈ 533 | ≈ 19 | ≈ 1 | 0 | 73% | 10 (2%) | 84% |
| Religion | 41 | 38 | 4 | 3 | 0% | 0 | 80% |

¹ *Map-ready* = in window and region, located, precision of a year or finer, and no conflicting claims.
Life, architecture and culture were measured on a seeded random sample of 3,000 items each and then extrapolated.
The stratum × subregion coverage tables are in `metrics.md`. War has no empty cell. Some empty cells in culture and
architecture (e.g. Balkans 901–950) are genuine data gaps, not sampling artefacts.

**Contract checks run on real statements.** The stable-ID self-test (§4.2) **passes in all five categories**:
shuffled order, reversed statements, an added alternative claim, a dropped statement, and whole-event removal
leading to `sourceMissing`. The occurrence-registry design holds up.

## 3. Findings that change the spec (proposed for v0.5)

Every item below was observed in the data. None of them is applied to `architecture.md` yet; they await your review.

### Dates (§4.3)

- **F1. WDQS silently converts dates.** WDQS returns a Julian **day**-precision date converted to Gregorian
  (Hastings: stored Julian 14 Oct 1066, returned as `1066-10-20`), but leaves coarser precisions as they are.
  → *Spec:* canonical dates come **only from entity JSON** (source calendar); WDQS values are used for discovery
  and never stored as the truth. The harness shows both paths give the same JD (t = 1066.819).
- **F2. "Century values ending in 00" are common:** 876 in architecture, 180 in culture, 83 in life. Wikidata reads
  `1100` at century precision as the **11th** century (1001–1100); the common shortcut `floor(Y/100)+1` gives the
  12th. → *Spec:* state `C = ceil(Y/100)` explicitly and add an acceptance test with `1100 → [1001, 1101)`.
- **F3. Millennium precision cannot be played back.** "2nd millennium" = `[1001, 2001)` overlaps the window, but its
  representative time (1501) is outside it (60 life events cluster there). → *Spec:* precision coarser than a century
  means **list-only**, never a map marker.
- **F4. The century pulse** (see decision D1). Under the v0.4 reveal rule, about **1,284 buildings and 411 life
  events would appear at the same instant around 1051**, and about 421 + 194 around 951. This is the biggest
  visual risk in Stage 1.

### Locations (§4.4)

- **F5. P276 locations need a precision derived from their target.** 43% of battle locations come through P276, and
  a P276 target can be a whole region (First Crusade → "Levant", drawn as a point at 34°N 36°E).
  → *Spec:* `precision` is derived from the target's type (settlement → `settlement`; region or country → `region`).
- **F6. P625/P276 on works is the current location.** Confirmed: the Bayeux Tapestry's coordinates are its museum.
  **P577 on manuscripts is a modern edition** (Exeter Book "published 1842").
  → *Spec:* culture never uses P625/P276, and ignores P577 for manuscript and codex types.
- **F7. Some events genuinely have more than one place.** The East–West Schism involves Rome and Constantinople.
  → *Spec (proposed):* keep the single `location` for Stage 1; multi-site events are curated as unlocated, with their
  places shown in the panel. Revisit `locations[]` in Stage 2.

### Scope and region evidence (§5.1)

- **F8. People carry their region in other properties:** P27 citizenship, P551 residence, P937 work location. Adding
  them raised retained life events from 794 to 1,077 (in the sample). → *Spec:* add them to the region-evidence list.
- **F9. The region-evidence rule drops the Schism.** It has no P625, P276, P17 or P710. The same applies to the
  Crusades umbrella item and the Council of Piacenza. → *Spec:* `curated/inclusions.yaml` is a **required input**
  for religion, not a rarely used escape hatch.

### Relationships (§4.5, §6)

- **F10. People link to wars through P607 ("conflict") on the person.** That gives about 366 person→battle
  links in the window, compared with about 15 via the battle's P710, which mostly lists polities.
  → *Spec:* import P607 as a `participant` relationship, indexed by `eventsInvolving`. This is the main source of
  links for life events.
- **F11. Architecture and culture are mostly unconnected** (88% and 84% have no link). Their connections will
  come from shared places and curation, not from imported properties.

### Pipeline (§5.2, §5.3)

- **F12. Discovery must include interval overlap.** Filtering on stored dates missed the **Reconquista (722–1492)**
  and turned the Arab–Byzantine wars into a false "1050–1060" event. → *Spec:* add span discovery
  (`start < windowEnd ∧ end ≥ windowStart`) and re-fetch full date records before resolving claims.
- **F13. Fetch the way Wikidata works best** (all of this was observed during the audit):
  - SPARQL for discovery only. Detail joins triggered HTTP 429 (query-time quota) and 502s.
  - **Entity JSON** (`wbgetentities`) for details: statement GUIDs, ranks, qualifiers, references and `lastrevid`,
    which is exactly the §4.6 provenance.
  - **Validate before caching.** WDQS returned HTTP 200 with truncated JSON followed by a Java stack trace; it was
    cached once, detected, and removed.
  - Split batches and year windows on repeated timeouts.
  - Direct `P31` (no subclass walk) for huge classes. The "literary work" subclass walk times out regardless of window.
  - `maxlag`: back off on database lag. When the lag is query-service lag, which only matters to editing bots,
    read-only entity fetches go ahead without `maxlag`.
- **F14. Titles need a fallback.** About a quarter of religion items have no English label (they display as QIDs or
  Catalan names). → *Spec:* title order en → mul → any label, tagged with its language; flagged in the validation report.
- **F15. The duplicate report needs geography.** 48 same-label pairs in architecture are mostly *different*
  churches with the same saint's name. → *Spec:* duplicate = same label + overlapping interval + within about 5 km.

## 4. Decisions needed from you

**D1. The century pulse (F4).** How should events dated only to a century behave during playback?
- **(a) Recommended:** off the playback map by default. They stay in the event list and search, plus an optional
  *"dated to century"* layer that shows them faintly for the whole century, with uncertainty styling. That keeps
  uncertainty separate from duration.
- (b) Reveal at the midpoint anyway, but only above a prominence threshold, so a handful pulse instead of hundreds.
- (c) Always show them faintly across the whole century. This is simplest, but it is the uncertainty-as-duration
  reading that review 2 ruled out.

**D2. How to choose people** (life has ≈ 1,000 map-ready people at ≥20 sitelinks). *Recommended:* people are
included when they are **connected**: P607 to an included war event, the subject of a sequence, or a ruler of a
polity in the sequences. On top of that, a small prominence top-up (≥40 sitelinks, map-ready).

**D3. Culture sourcing.** *Recommended:* a curated list for Stage 1 (≈ 30 works), each with a reviewed creation
place and its evidence, e.g. *Book of Optics* → Cairo, *Canon of Medicine* → Hamadan, *Bayeux Tapestry* → England
(probably Canterbury), *Gero Cross* → Cologne. Automatic import returns in Stage 2 if P1071 coverage improves.

**D4. Religion seeds.** *Recommended:* automatic import of councils and synods, plus ≈ 8 curated seeds: the East–West
Schism, Investiture Controversy, Walk to Canossa, Christianization of Kievan Rus', Peace and Truce of God, Cluniac
reform, Council of Clermont (already imported), and the Rhineland massacres (already imported).

## 5. Proposed Stage 1 dataset (≈ 250–300 events)

| Source | Rule | Est. events |
|---|---|---|
| War | Automatic: map-ready, sitelinks ≥ 10 | ≈ 104 |
| Life | Connected people (D2) + prominence top-up | ≈ 60–80 |
| Architecture | Automatic: map-ready, year precision, sitelinks ≥ 20 | ≈ 77 (≈ 40 if ≥ 30) |
| Religion | Automatic councils and synods (all 38 map-ready) + curated seeds (D4) | ≈ 45 |
| Culture | Curated (D3) | ≈ 30 |
| Sequences | The 5 agreed sequences, built from the events above | — |

This sits within the 100–300 target for the connected prototype, leaving room to trim after the first render.

## 6. Harness notes and limits

- The harness in `pipeline/audit/` is labelled **throwaway**. Its rules (`rules.py`) will be re-implemented
  with tests in the production pipeline; the findings above are what carries over.
- Life, architecture and culture metrics come from seeded random samples of 3,000 and are extrapolated. The CSV
  samples are stratified with hard cases added, for manual checking, and are **not** the basis of the percentages.
- Types were verified against Wikidata on 2026-09-24/25. The culture and life categories use direct `P31` only,
  so works typed with a subclass not in the list are missed. That is another reason to curate culture in Stage 1.
- Wikidata had sustained query-service lag (up to about 450 s) during the run. It affected speed, not the results.
