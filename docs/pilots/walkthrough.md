# Walkthrough gate — results (2026-09-28)

> App: `web/` (Vite + TypeScript + MapLibre GL + deck.gl), run with `npm --prefix web run dev` and checked in the
> browser pane against the shared pilot dataset `web/public/data/pilot/` (177 entities, 209 events,
> 400 relationships). Observed values below were read from the running app. Screenshots were
> taken in-session only and are not stored in the repo.

| # | Gate check (spec v1.0 §11) | Result | What was observed |
|---|---|---|---|
| 1 | Event → person → event | ✅ | Reading path step 8 opens **Battle of Hastings** (14 Oct 1066, Julian; step bar "8/9"); participants with tiers (Harold ✓✓ verified, Gyrth ✓ single-source). → **Harold Godwinson**: Family 8 (father Godwin, mother Gytha, siblings Edith, Tostig, Gyrth…), Marriage (Ealdgyth, 1064), House, Office (Monarch of England, 5 Jan – 14 Oct 1066), Took part (Hastings ✓✓, Stamford Bridge ✓). → **Battle of Stamford Bridge** (25 Sep 1066; step "6/9"): Tostig ✓✓, Harald III ✓, Harold ✓ |
| 2 | Unlocated item explored fully | ✅ | **Road to Canossa** shows "No map location — explore through its connections" before its curated place was added; its participants (Gregory VII, Henry IV, Hugh of Cluny, Matilda — all ✎ curated) and "part of Investiture controversy" are navigable. The **East–West Schism** stays unlocated (no place in Wikidata; distributed by nature) and is reachable from the story path, search and Leo IX |
| 3 | Path crossing the two pilots through shared records | ✅ | **Emma of Normandy** → daughter **Gunhilda of Denmark** → spouse **Henry III** (10 Jun 1036, ✓✓, shown with a "↗ Church reform…" chip) → the chip switches story → Henry III's page lists his son **Henry IV** (→ Canossa) and a chip back to the 1066 story. Found by the pipeline from Wikidata alone. A second family bridge: **Judith of Flanders** (Tostig's wife) → her son **Welf** (married Matilda of Tuscany) |
| 4 | Readable explanation + inspectable evidence | ✅ | Every link opens to its explanation, the Wikidata statements (entity · property · statement id · revision) and their references, or the curated sources. Hugh of Cluny → Canossa shows the source *and* its ⚠ uncertainty note |
| 5 | Missing evidence stays visible | ✅ | Emma: "House of Wessex" and "Queen consort of Denmark" shown as **? unverified**. Conflicts shown, not fixed (e.g. Gytha → Sweyn: parent born < 12 years before child). Reading-path steps without evidenced links are flagged |
| 6 | Map, timeline and relationships together | ✅ | Playback at 1066.70 → 1066.79 → 1067: Fulford and Stamford Bridge appear together (late Sept 1066), with the deaths of Harald III and Tostig; Hastings and Harold's death follow; by 1075 the Harrying of the North, Siege of Exeter and Ely Rebellion appear while 1066 fades. Selecting a record moves the timeline and map; path steps open records |

**Kinds are visibly distinct** (colour-coded groups: Family, Marriage, House, Offices, Took part, Founding,
Affiliation, Historical claims), and tier badges appear on every link: ✓✓ verified, ✓ single-source, ? unverified,
! conflict, ✎ curated.

## Issues found during the walkthrough, and fixed

- MapLibre worker failed under Vite pre-bundling → `optimizeDeps.exclude`.
- deck.gl interleaved overlay incompatible with MapLibre v6 → overlaid mode (MapLibre still owns the camera).
- Antimeridian-crossing land polygons smeared across the Atlantic → rings are unwrapped; Antarctica dropped.
- Reading-path steps only moved the timeline → they now open the record, with previous/next navigation.
- Wikidata types *Road to Canossa* as an idiom → curated correction on the seed (kind, place, source); Wikidata's
  own Dec 1076 – Jan 1077 dates take precedence over the curated date.
- "Crusader states" classified the Kingdom of Jerusalem as an event → strong polity markers checked first.

## Not yet tested

Users other than the builder; culture and science (next: Bayeux Tapestry); mobile layout beyond a basic breakpoint.
