# HistoryMap — Architecture (v1.0-draft, connection-led)

> Branch: `connection-led`. `main` keeps v0.4 (volume-oriented) and the Milestone 1 audit.
> Status: **draft**, validated by two pilot stories and an interactive walkthrough before Stage 1 planning.
> Reviews in `docs/reviews/`; audit corrections in `docs/audit/errata.md`. 🟡 = default to tune from evidence.

## 0. Why this version exists, and what changed

The goal is **not** to collect as many data points as possible, but to **show connections**. v0.4 selected
per-category lists by thresholds and added links afterwards. v1.0 inverts that: **curated stories and anchors →
relationships fetched in both directions → supporting records admitted only with an evidenced, relevant link**.
Inclusion and map presentation are separate decisions.

| Source | Point | Where addressed |
|---|---|---|
| Brief 1 | Demonstrate connections, not volume | §1, §3, §11 |
| Brief 2 | People only if connected (wars, polities, religion, architecture, works, science) | §6.2, §7 |
| Brief 3 | Architecture threshold by historical/cultural significance | §7.3 |
| Brief 4 | Rulers' family and marriage connections | §5.2, §10.3 |
| Brief 5 | Culture/religion by significance, without hard geo-location | §7.4, §8.4 |
| Brief 6 | Balance fetching and curation | §9 |
| Review 3 | Stories first; roles; one-step expansion; P39 tenure; war ≠ battles; building ≠ construction event; location assessment, not coordinates; errata | §3, §6, §7, §9, errata |
| Review 4 | Shared identities + story membership; explicit normalisation to events; corrected relationship semantics; explanation-grade evidence; investigate-not-assume framing; three-state overlap; cross-checks; walkthrough gate | §2–§6, §8, §10, §11 |

**Carried over from v0.4 unchanged:** occurrence registry and IDs (§4), HistDate and the four time notions (§4.2),
Location (§4.3), Provenance (§4.4), determinism invariant (§10.4), stage windows in `pipeline/config/scope.yaml`,
stack (MapLibre GL camera owner + deck.gl `MapboxOverlay`, static data, no backend).

## 1. Goals and scope

| | |
|---|---|
| Purpose | Personal prototype proving **connected exploration** of history; publishable later |
| Unit of selection | A **story** (a curated question or theme) — an entry point into one shared dataset (§3) |
| Region | Europe + Mediterranean + Anatolia/Levant (bbox in `scope.yaml`) — for *event* scope and map framing, not for admitting entities |
| Time | Stage window in `scope.yaml` (Stage 1: 901–1099 CE, Julian, half-open). Events: interval-overlap rule. Supporting entities: activity overlap (§7.1) |
| Pilots (gate) | **1066 succession crisis** · **Church reform, papal authority, and the First Crusade** |
| What the pilots test | Family/marriage, rulers and claims, military events, religious institutions and disputes, some architecture |
| What they do **not** test | Culture and science. Next: Bayeux Tapestry (connects to the women of 1066); later a science pilot (authorship, transmission, translation, institutions) |

**Non-goals:** causal inference from data; completeness; accounts/editing UI; backend.

## 2. The shared dataset

**One identity per thing.** Every person, polity, office, dynasty, institution, building, work, movement and event
has exactly one global ID across all stories (QID-based, §4). Relationships are shared records. Stories never own
records; they *refer* to them.

```
                 ┌──────────────── shared dataset ────────────────┐
  Story A ──┐    │ Entity ── Relationship ── Entity                │
            ├──► │   │                         │                   │
  Story B ──┘    │ Event ─── Relationship ── Event                 │
  (membership,   │ Presentation (marker / timeline / span / panel) │
   path, exits)  └─────────────────────────────────────────────────┘
```

| Record | Purpose |
|---|---|
| `Entity` | Person, polity, office, dynasty, institution, building, work, movement, place |
| `HistEvent` | Something that happened, with timing (§4.2) and optional location |
| `Relationship` | A sourced statement connecting two records (§5) |
| `Story` | Title, framing **question**, window |
| `StoryMembership` | `{story, ref, role, explanation, sources}` — the role lives **here**, not on the entity |
| `StoryPath` | Editorial reading order + onward exits (§3.3) — **never** a historical relationship |
| `Presentation` | How a record appears: marker / timeline / context span / panel-only (§8) |

Per-story files are **views** (filters over the shared dataset). Merging any views yields no duplicates because
IDs are global. Moving from one story to another is navigation within one dataset, not opening another.

## 3. Stories as entry points

### 3.1 Membership roles (per story)

| Role | Meaning |
|---|---|
| `anchor` | Curated; central to the story; carries a significance sentence and source |
| `connecting` | Admitted because it has an evidenced, relevant relationship to the story's anchors |
| `context` | Helps interpret the story (e.g. a predecessor, a founding abbot); shown as context, not active in playback |
| `candidate` | Found by expansion; not published until relevance rules or review admit it |

The same person can be an `anchor` in one story and `context` in another.

### 3.2 Framing

A story is a **question to investigate**, not a predetermined chain. Pilot 2 is "Church reform, papal authority,
and the First Crusade", not "reform → crusade". Its connections are labelled independently (affiliation, personal
involvement, shared concern, conflict, chronology, influence) and may branch, disagree, or be missing.

### 3.3 Paths and onward exits

`StoryPath` = ordered steps with a short note each ("next in this story" — editorial). `exits` = connected records
beyond the narrative ("continue exploring"), so a story never dead-ends: e.g. First Crusade → Alexios I's appeal,
Rhineland massacres, Kingdom of Jerusalem; 1066 → Harrying of the North, Domesday. Crossing into another story
through a **shared record** is shown explicitly.

## 4. Identity and time (carried over from v0.4)

### 4.1 Occurrence registry
`pipeline/registry/occurrences.json`, committed and append-only. First occurrence of `(entity, eventType)` =
`"{qid}:{eventType}"`; additional **distinct** occurrences = `"{qid}:{eventType}:{key}"` (key from the SHA-1 of
the first evidencing statement GUID, minted once). Multiple values of one property default to **alternative claims
about one event**; distinct occurrences need positive evidence (P793 items, P1545 ordinals, curated split);
non-overlapping claims with no deciding rank → `needsReview`, never auto-split. Vanished statements →
`sourceMissing`; IDs are never reused. Relationship IDs follow the same rule: `"{from}>{type}>{to}"`, stable.

### 4.2 Time
Unchanged from v0.4 §4.3: dates converted from their **source calendar** to Julian Day (canonical values come from
entity JSON — WDQS converts day-precision Julian dates, audit F1); half-open bounds by precision with
`century C = ceil(Y/100)` (audit F2); possible interval / representative time / reveal rule / fade reference as
four separate notions. Precision coarser than a century is list-only (audit F3).

```ts
interface HistDate { raw; precision; calendar; earliestJd; latestJd /* exclusive */; circa?; statementId }
interface Timing   { temporalKind: "point" | "span" | "openSpan"; start: HistDate; end?: HistDate }
```

### 4.3 Location
v0.4 `Location {lat, lon, role, precision, source}`, plus: `precision` is **derived from the target's type**
(settlement vs region; audit F5); works never use P625/P276 (current holding location) and manuscripts never use
P577 (modern edition; audit F6). Every record carries a **location assessment**: `located` / `unknown` /
`distributed` (e.g. East–West Schism) / `not-applicable` (offices, dynasties). A coordinate is never required.

### 4.4 Provenance
v0.4 `Provenance` (claims with entity, property, statement ID, entity revision; extractor version; override;
sources), extended by §5.4.

## 5. Relationships

### 5.1 Three layers

| Layer | Example | Source |
|---|---|---|
| `relationship` | Emma of Normandy was married to Cnut | Imported or curated |
| `claim` | William claimed the English throne | Curated, sourced — records that a historical actor asserted something |
| `interpretation` | Emma's marriages connected the English and Danish royal houses | Curated, sourced — significance; never auto-published |

A family relationship can help explain a succession claim without establishing that the claim was legitimate;
the UI shows the three layers distinctly.

### 5.2 Kinds and semantics

| Kind | Type(s) | Wikidata source | Rules |
|---|---|---|---|
| kinship | `fatherOf`, `motherOf`, `parentOf` | P22, P25 on the child; P40 on the parent | P22/P25 give father/mother. A reverse **P40 alone gives neutral `parentOf`** (P40 does not say which parent). Merge both directions into one link |
| marriage | `spouseOf` | P26 (symmetric) | Keep P580/P582 dates and **P2842 place of marriage**. "Married to" ≠ "political alliance" (that is an interpretation) |
| dynasty | `memberOfDynasty` | P53 | Target type `dynasty/family` |
| office | `heldOffice` | P39 + qualifiers P580/P582, P1365/P1366 (replaces / replaced by) | A **temporal relationship**, not an event. Jurisdiction from the office item's **P1001**. An occupation ("monarch") never implies "ruled X". P642 is not used (no longer available) |
| participation | `participatedIn` | P607 on the person; P710 on the event | Participation in a **war** is never expanded into its battles |
| affiliation | `memberOf`, `religiousOrder` | P463, P611 | Institutional affiliation, not shared belief |
| founding | `founded`, `commissioned`, `architectOf` | P112, P88, P84 | Check the building **phase** the claim describes |
| authorship | `authorOf`, `creatorOf`, `discovererOf` | P50, P170, P61 (on the work) | **P800 (notable work) only discovers candidates**; the role must be verified through these properties |
| structure | `partOf`, `precedes` | P361, P155/P156 | `partOf` = membership (never expanded pairwise) |
| chronology | `precedes` (derived) | derived from dates | Labelled "came before", never "led to" |
| shared concern / conflict / influence | curated types | `curated/connections.yaml` | Interpretive or claim layer; sources required |

Target types admitted: person, polity, **office**, **dynasty**, **institution**, **movement**, building, work,
event, place.

### 5.3 Deduplication

One **displayed** link per `(from, type, to)`; it keeps **every supporting statement** (from both sides) and any
**conflicting dates** side by side. Inverse pairs (P40 ↔ P22/P25) and symmetric pairs (P26 on both spouses) merge.

### 5.4 Evidence and explanation

```ts
interface Relationship {
  id: string; kind: Kind; type: string; layer: "relationship" | "claim" | "interpretation";
  from: Ref; to: Ref;
  time?: { start?: HistDate; end?: HistDate };
  overlap: "overlapping" | "not-overlapping" | "unknown";      // with the stage window (§7.1)
  qualifiers?: { placeOfMarriage?: Ref; jurisdiction?: Ref; replaces?: Ref; replacedBy?: Ref };
  statements: Array<{ entity: string; property: string; statementId: string; revision: number;
                      rank: string; references: Reference[]; time?: {...} }>;
  conflicts?: string[];                                        // e.g. differing dates between statements
  explanation: string;                                         // short, readable
  uncertainty?: string;                                        // competing claims / interpretations
  tier: "verified" | "supported" | "review" | "conflict" | "curated";   // §10
  status: "published" | "candidate" | "rejected";
  provenance: "imported" | "derived" | "curated";
}
interface Reference { strength: "strong" | "weak" | "none"; statedIn?: Ref; url?: string; importedFrom?: string; retrieved?: string }
```

- A source attached to a **seed** does not support that seed's relationships. Each link carries its own evidence.
- Imported explanations are generated from the assertion ("Wikidata records Cnut as a spouse of Emma of Normandy
  (1017–1035)") and show the reference detail, not a count.
- **Curated connections** live in `pipeline/curated/connections.yaml`: endpoints, type, layer, explanation, sources,
  status.
- **Review decisions** live in `pipeline/curated/decisions.yaml`, keyed by relationship ID; rebuilds preserve them.

## 6. Normalisation: from selected claims to playable content

Knowing that Harold exists and fought at Hastings is not the same as producing playable content. The **normalise**
stage turns selected source claims into:

| Output | Example | Rule |
|---|---|---|
| Canonical dated **events** | Battle of Hastings (14 Oct 1066, Julian) | Timing via §4.2 and claim resolution |
| **Participation** links | Harold → Hastings, William → Hastings | From P607/P710; war ≠ battles |
| Relevant **life events** | Birth/death of Emma | Only for admitted people; shown when they aid the story |
| **Office tenures** | Edward the Confessor, King of England 1042–1066 | Temporal **relationships**, drawn as spans on the timeline, not events |
| **Institutions** | Cluny Abbey | The institution's existence ≠ a construction event; a *founding* event only when dated (910) |
| **Presentation records** | marker / timeline / span / panel | §8 |

Entities are kept even when they produce no marker. No dated event is manufactured just because an entity was admitted.

## 7. Admission

### 7.1 Activity overlap (supporting entities)

Three states: **overlapping** (a dated activity — office tenure, participation, founding, authorship, marriage —
overlaps the window), **not overlapping**, **unknown** (activity undated). **Unknown → review**, never automatic
exclusion. Birth/death alone never admits anyone.

**Historical-context exception (reviewed):** a predecessor, founder or ancestor outside the window may be admitted
as `context` when it explains an in-window institution or claim (e.g. William I of Aquitaine founding Cluny in
910). Context entities do not appear as active in playback and do not widen the window.

### 7.2 Candidates and publication

Straightforward imported claims enter as **candidates**. Type, period and a selected target establish *technical
eligibility*, not historical importance. Publication follows explicit relevance rules (a link on a story path,
kinship/marriage/office between admitted people, participation in an admitted event) plus the verification tier
(§10), or review. "Same country / religion / century" and birth↔death alone never qualify.

### 7.3 Architecture

Historical role first: cathedrals, major abbeys, royal/political centres, major mosques, important fortifications
are prioritised for review; ordinary local buildings excluded by default, with reviewed exceptions for a documented
role (a council, coronation, work). Sitelinks order the review queue and never veto. A type count ("church
building") measures discovery volume; it never classifies a building as a parish church. A building/institution
is separate from its construction event; century-dated sites stay as context without an invented construction event.

### 7.4 Culture and religion

Curated anchor IDs + automated enrichment (creators, participants, institutions, dates, references). Work ≠
manuscript/fragment/edition. A **location assessment** is required, not a coordinate. Not every located council or
synod is admitted — each needs a meaningful institutional, doctrinal, political or personal connection. Each
anchor records *why it matters to the period or story, and what source supports that*.

## 8. Presentation

- **Event markers** (located events) and **timeline** entries follow the v0.4 reveal/fade rules. **Arcs** connect
  located event↔event links only.
- **Entity relationships** (kinship, marriage, office, affiliation) appear in a compact **relationship view in the
  side panel**, grouped by kind — never as arcs between birthplaces.
- **Office tenures** appear as timeline spans on the entity's panel.
- **Unlocated records** (Emma of Normandy, the Investiture Controversy, the East–West Schism) take full part through
  the panel, timeline and search.
- **Century-dated items** (audit D1): list/panel by default; an optional "dated to century" layer shows them faintly
  with uncertainty styling.
- Kinds are visually distinct: kinship · marriage · participation · office · affiliation · chronology ·
  claim · interpretation. Tier badges on every link; "evidence missing" is shown, never papered over.

## 9. Fetching workflow (balance of curation and automation)

Curation supplies **selection, missing connections, interpretation, corrections**. Automation supplies
**identities, claims, references, repeatable enrichment, cross-checks**.

1. **Curate seeds** per story (`pipeline/curated/stories/*.yaml`): English Wikipedia titles resolved to QIDs at build
   time; role, significance, source; path and exits.
2. **Re-extract** relationships from cached entity JSON (the cache is indexed by QID and `lastrevid`, so batch
   composition never forces a re-download).
3. **Fetch missing immediate neighbours only** — entity batches of 50 and small reverse queries scoped to selected IDs
   (`VALUES ?seed {…} ?x wdt:P710|wdt:P607|wdt:P40|wdt:P26 ?seed`). No global discovery.
4. **Resolve metadata** (labels, office jurisdictions, place coordinates) — does not consume the expansion step.
5. **Expand a second step only for a named gap** declared in the story file.
6. **Cross-check** (§10), **normalise** (§6), **generate** the shared dataset and per-story views + reports.

Discovery rules learned in the audit remain for later broad stages: SPARQL for discovery only; entity JSON for
details; validate before caching; split batches/windows on timeouts; direct P31 for huge classes; maxlag handling.

## 10. Verification tiers and cross-checks

The user decides editorial emphasis and genuinely ambiguous cases; the pipeline does the fact-checking legwork.

| Check | Examples | Failure → |
|---|---|---|
| **Logical constraints** (JD) | parent born ≥ 12 years before child, alive (or ≤ 1 year dead for fathers) at birth; marriage within both lifetimes; participant alive at event; tenure within lifetime | `conflict` |
| **Agreement within Wikidata** | P26 on both spouses; P22/P25 matching the parent's P40 | disagreement → `conflict` |
| **Reference quality** | P248 stated-in / P854 URL = strong; P143 imported-from-Wikimedia only = weak; none | lowers tier |
| **Independent corroboration** | English Wikipedia article of one endpoint links to the other's article (MediaWiki `prop=links`) | lowers tier |

| Tier | Rule | Publication |
|---|---|---|
| `verified` | logic OK ∧ (agreement ∨ strong reference) ∧ corroborated | auto-publish |
| `supported` | logic OK ∧ at least one of agreement / reference / corroboration | publish, marked "single-source" |
| `review` | logic OK, nothing supports it — or overlap unknown | review list |
| `conflict` | constraint failed or sources disagree | shown as conflict; review list |
| `curated` | from `connections.yaml` with its own sources | as reviewed |

Claim and interpretation layers are never auto-published. The review list shown to the user holds only `review` /
`conflict` items **on a story path** plus editorial choices; the report states every rule applied.

### 10.4 Determinism
v0.4 invariant, extended: for the same dataset and state `(t, viewport, zoom, filters, mode, selection, story, path
step)`, the rendered set and styles are identical regardless of navigation history.

## 11. Success criteria (the walkthrough gate)

Before Stage 1 planning, the pilots and walkthrough must show:

- [ ] A reader follows a meaningful path **event → person → event/institution**, with onward exits beyond the story.
- [ ] One path **crosses between the two pilots through shared records**.
- [ ] Each important connection has a **readable explanation and inspectable evidence**.
- [ ] **Kinship, participation, chronology and interpretation** are visibly distinguishable.
- [ ] An **unlocated item** participates fully in exploration.
- [ ] **Missing evidence stays visible** rather than being replaced by an inferred link.
- [ ] A small **interactive walkthrough** demonstrates map selection, timeline navigation and relationship
      exploration together.

Metrics reported per story: anchors with complete explainable paths; people linked to an admitted event, office,
institution or work; cross-category links; links with evidence and temporal context; items admitted without
coordinates; tiers distribution; review-list size.

## 12. Next after the gate

Stage 1 planning on this branch (writing-plans); Bayeux Tapestry culture extension (creation, depiction,
patronage, interpretation treated separately); science pilot; historical-basemaps licence check (GPL-3.0 vs the
repo's CC0) before bundling borders.
