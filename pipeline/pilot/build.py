"""Pilot build — one shared connected dataset from curated stories (PROTOTYPE, spec v1.0-draft §9).

    python pipeline/pilot/build.py

Writes web/public/data/pilot/ (shared dataset + per-story views) and docs/pilots/*.md (reports).
Mostly served from cache; every new request is counted and reported.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.dont_write_bytecode = True

import common  # noqa: E402,F401  (puts pipeline/audit on the import path)
import wbapi  # noqa: E402
import wdqs  # noqa: E402
from common import CURATED, DATA_OUT, REPORTS, STAGE, R, hist_date, label, load_yaml, snak_item, write_json  # noqa: E402
from crosscheck import assess, explain, fmt_date, lifetimes  # noqa: E402
from entity_store import EntityStore, linked_qids, mw_stats, resolve_titles, reverse_links  # noqa: E402
from expand import Membership, admit, classify, find_gap_path  # noqa: E402
from normalize import normalize, save_registry  # noqa: E402
from relations import REVERSE_PROPS, Relationship, extract, merge, rel_id  # noqa: E402

PUBLISH_TIERS = {"verified", "supported", "curated"}
PARENT_TYPES = {"fatherOf", "motherOf", "parentOf"}


def main() -> None:
    stories = [load_yaml(p) for p in sorted((CURATED / "stories").glob("*.yaml"))]
    curated = load_yaml(CURATED / "connections.yaml").get("connections") or []
    decisions = load_yaml(CURATED / "decisions.yaml").get("decisions") or {}

    # 1 — resolve every curated title to a QID (never guessed)
    titles = set()
    for st in stories:
        for key in ("seeds", "path", "exits"):
            titles |= {x["title"] for x in st.get(key, [])}
        titles |= {s["override"]["place"] for s in st["seeds"] if s.get("override", {}).get("place")}
        for g in st.get("gaps", []) + st.get("expect", []):
            titles |= {g["from"], g["to"]}
    for c in curated:
        titles |= {c["from"], c["to"]}
    qmap = resolve_titles(sorted(titles))
    unresolved = sorted(t for t, q in qmap.items() if not q)
    print(f"[titles] {len(qmap)} resolved, {len(unresolved)} unresolved: {unresolved}")

    store = EntityStore()
    seeds = {st["id"]: {qmap[s["title"]]: s for s in st["seeds"] if qmap.get(s["title"])} for st in stories}
    exits = {st["id"]: {qmap[e["title"]]: e for e in st.get("exits", []) if qmap.get(e["title"])} for st in stories}
    S = set().union(*seeds.values())
    E = set().union(*exits.values())
    ents = store.get(S | E)

    # 2 — one step: outgoing statements of seeds + scoped incoming statements
    out_targets = {a.to if a.from_ == q else a.from_ for q in S if q in ents for a in extract(ents[q])}
    incoming = reverse_links(sorted(S), REVERSE_PROPS)
    N = (out_targets | {x for x, _, _ in incoming}) - S - E
    ents.update(store.get(N))
    print(f"[expand] seeds {len(S)}, exits {len(E)}, one-step neighbours {len(N)} "
          f"({len(incoming)} incoming statements); entities fetched so far {store.fetched}")

    def relations_now() -> dict[str, Relationship]:
        ids = set(ents)
        return merge([a for q in ids for a in extract(ents[q]) if a.from_ in ids and a.to in ids])

    # 3 — second step, named gaps only
    gap_members: dict[str, dict[str, str]] = defaultdict(dict)
    gap_report = []
    rels = relations_now()
    for st in stories:
        for g in st.get("gaps", []):
            a, b = qmap.get(g["from"]), qmap.get(g["to"])
            path = find_gap_path(a, b, store, ents, rels) if a and b else None
            gap_report.append((st["id"], g, path))
            for x in (path or [])[1:-1]:
                gap_members[st["id"]][x] = f"links {g['from']} and {g['to']} (named gap: {g['note']})"
    rels = relations_now()

    # 4 — metadata: class labels for classification (does not count as expansion)
    classes = {snak_item(s["mainsnak"]) for e in ents.values() for s in e.get("claims", {}).get("P31", [])}
    class_ents = store.get({c for c in classes if c})
    class_labels = {q: label(e, q)[0] for q, e in class_ents.items()}
    kinds, class_names = {}, {}
    for q, e in ents.items():
        kinds[q], class_names[q] = classify(e, class_labels)
    # Curated corrections on seeds (kind, event type, date, place) — each with its own source.
    overrides = {}
    for st in stories:
        for s in st["seeds"]:
            q, ov = qmap.get(s["title"]), s.get("override")
            if q and ov:
                overrides[q] = {**ov, "placeQid": qmap.get(ov.get("place", ""))}
                if ov.get("kind"):
                    kinds[q] = ov["kind"]
    names = {q: label(e, q)[0] for q, e in ents.items()}

    # 5 — memberships per story (roles live on memberships, not entities)
    memberships: list[Membership] = []
    for st in stories:
        sid = st["id"]
        members: dict[str, str] = {}
        for q, s in seeds[sid].items():
            memberships.append(Membership(sid, q, s["role"], s["significance"], [s["source"]], rule="curated seed"))
            members[q] = s["role"]
        for q, why in gap_members[sid].items():
            if q not in members:
                memberships.append(Membership(sid, q, "connecting", why, rule="named gap (second step)"))
                members[q] = "connecting"
        admitted_here = admit(sid, members, set(ents) - set(exits[sid]), kinds, rels, ents, names)
        memberships += admitted_here
        # Exits are destinations, not expansion starting points: added after admission, never expanded from.
        taken = set(members) | {m.ref for m in admitted_here if m.role != "candidate"}
        for q, e in exits[sid].items():
            if q not in taken:
                memberships.append(Membership(sid, q, "context", f"Onward exit: {e['note']}", rule="curated exit"))

    # 6 — curated connections (own sources; never auto-tiered)
    for c in curated:
        a, b = qmap.get(c["from"]), qmap.get(c["to"])
        if not (a and b):
            continue
        r = rels.get(rel_id(a, c["type"], b)) or Relationship(rel_id(a, c["type"], b), c["kind"], c["type"], a, b)
        r.layer, r.provenance, r.tier = c.get("layer", "relationship"), "curated", "curated"
        r.explanation, r.sources = " ".join(c["explanation"].split()), c.get("sources", [])
        r.uncertainty = " ".join(c.get("uncertainty", "").split())
        r.status = "published" if c.get("status") == "accepted" else "candidate"
        if c.get("time", {}).get("start"):
            y = int(str(c["time"]["start"])[:4])
            r.time["start"] = hist_date({"time": f"+{y:04d}-00-00T00:00:00Z", "precision": 9, "calendar": R.JULIAN})
        rels[r.id] = r

    admitted = {m.ref for m in memberships if m.role != "candidate"}

    # 7 — metadata for admitted records: places, marriage places, reference sources, office jurisdictions
    meta = set()
    for q in admitted:
        for p in ("P276", "P19", "P20", "P1001"):
            meta |= {snak_item(s["mainsnak"]) for s in ents.get(q, {}).get("claims", {}).get(p, [])}
    meta |= {ov["placeQid"] for ov in overrides.values() if ov.get("placeQid")}
    for r in rels.values():
        meta |= {r.qualifiers.get("placeOfMarriage")}
        meta |= {ref.get("statedIn") for s in r.statements for ref in s.get("references", [])}
    ents.update(store.get({m for m in meta if m} - set(ents)))
    names.update({q: label(e, q)[0] for q, e in ents.items() if q not in names})

    # 8 — cross-checks on links between admitted records
    people = {q for q in admitted if kinds.get(q) == "person"}
    life = lifetimes(ents, people)
    links = {}
    for q in sorted(admitted):
        title = ents.get(q, {}).get("sitelinks", {}).get("enwiki", {}).get("title")
        if title:
            links[q] = linked_qids(title)
    published_rels = []
    for r in rels.values():
        if r.from_ not in admitted or r.to not in admitted:
            continue
        if r.provenance != "curated":
            assess(r, life, ents, links)
            explain(r, names, names)
            r.status = "published" if r.tier in PUBLISH_TIERS and r.layer == "relationship" else "candidate"
        d = decisions.get(r.id)
        if d:
            r.status = "published" if d.get("decision") == "accept" else "rejected"
            r.checks["decision"] = d
        published_rels.append(r)
    print(f"[crosscheck] {len(published_rels)} links between admitted records; tiers "
          f"{dict(Counter(r.tier for r in published_rels))}")

    # 9 — normalise into events and presentation records
    anchors = {m.ref for m in memberships if m.role == "anchor"}
    events, presentation, registry = normalize({q: 1 for q in admitted}, kinds, ents, class_labels,
                                               published_rels, anchors, overrides)
    save_registry(registry)

    # 10 — write the shared dataset + per-story views
    write_outputs(stories, qmap, memberships, admitted, ents, kinds, class_names, names, events, presentation,
                  published_rels, life)
    write_reports(stories, qmap, memberships, admitted, kinds, names, published_rels, events, presentation,
                  gap_report, unresolved, store)
    print(f"[done] entities fetched {store.fetched}; wbapi requests {wbapi.stats['requests']}; "
          f"wdqs requests {wdqs.stats['requests']}; enwiki requests {mw_stats['requests']} "
          f"(cache hits: wbapi {wbapi.stats['hits']}, wdqs {wdqs.stats['hits']}, enwiki {mw_stats['hits']})")


# ---------------------------------------------------------------- outputs


def entity_record(q, ents, kinds, class_names, names, life, memberships):
    e = ents.get(q, {})
    lbl, lang = label(e, q)
    rec = {"id": q, "kind": kinds.get(q, "other"), "label": lbl, "labelLang": lang,
           "description": e.get("descriptions", {}).get("en", {}).get("value", ""),
           "classes": class_names.get(q, [])[:4], "revision": e.get("lastrevid"),
           "wikidata": f"https://www.wikidata.org/wiki/{q}"}
    t = e.get("sitelinks", {}).get("enwiki", {}).get("title")
    if t:
        rec["wikipedia"] = "https://en.wikipedia.org/wiki/" + t.replace(" ", "_")
    if q in life:
        rec["lifespan"] = {k: fmt_date(v) for k, v in life[q].items() if v}
    rec["stories"] = [{"story": m.story, "role": m.role} for m in memberships if m.ref == q and m.role != "candidate"]
    return rec


def write_outputs(stories, qmap, memberships, admitted, ents, kinds, class_names, names, events, presentation,
                  rels, life):
    entities = [entity_record(q, ents, kinds, class_names, names, life, memberships) for q in sorted(admitted)]
    story_recs = []
    for st in stories:
        sid = st["id"]
        story_recs.append({
            "id": sid, "title": st["title"], "question": " ".join(st["question"].split()), "window": st["window"],
            "memberships": [m.to_json() for m in memberships if m.story == sid and m.role != "candidate"],
            "path": [{"ref": qmap.get(p["title"]), "note": p["note"]} for p in st.get("path", []) if qmap.get(p["title"])],
            "exits": [{"ref": qmap.get(p["title"]), "note": p["note"]} for p in st.get("exits", []) if qmap.get(p["title"])],
        })
    rel_json = [r.to_json() for r in sorted(rels, key=lambda r: r.id)]
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    write_json(DATA_OUT / "entities.json", entities)
    write_json(DATA_OUT / "events.json", sorted(events, key=lambda e: (e["year"], e["id"])))
    write_json(DATA_OUT / "relationships.json", rel_json)
    write_json(DATA_OUT / "stories.json", story_recs)
    write_json(DATA_OUT / "presentation.json", presentation)
    for sr in story_recs:
        refs = sorted({m["ref"] for m in sr["memberships"]})
        write_json(DATA_OUT / "views" / f"{sr['id']}.json", {"story": sr["id"], "refs": refs,
                   "relationships": sorted(r.id for r in rels if r.from_ in refs and r.to in refs)})
    write_json(DATA_OUT / "manifest.json", {
        "dataset": "pilot", "spec": "v1.0-draft", "built": date.today().isoformat(),
        "stage": STAGE, "stories": [s["id"] for s in stories],
        "counts": {"entities": len(entities), "events": len(events), "relationships": len(rel_json),
                   "published": sum(1 for r in rels if r.status == "published")},
        "sources": [{"name": "Wikidata", "licence": "CC0-1.0"},
                    {"name": "English Wikipedia (link graph for corroboration only)", "licence": "CC BY-SA 4.0 (not redistributed)"}],
    })


# ---------------------------------------------------------------- reports


def short_ev(r) -> str:
    if r.provenance == "curated":
        return "curated: " + ", ".join(r.sources[:2])
    parts = []
    for s in r.statements[:3]:
        refs = s.get("references", [])
        best = next((x for x in refs if x["strength"] == "strong"), refs[0] if refs else None)
        tag = ("stated in " + best.get("statedIn", "?") if best and best.get("statedIn") else
               "URL" if best and best.get("url") else "imported from Wikimedia" if best and best["strength"] == "weak"
               else "no reference")
        parts.append(f"{s['entity']}/{s['property']} ({tag})")
    return "; ".join(parts)


def expect_check(e, qmap, rels) -> tuple[str, str]:
    a, b = qmap.get(e["from"]), qmap.get(e["to"])
    if not (a and b):
        return "unresolved", ""
    want = PARENT_TYPES if e["type"] == "parent" else {e["type"]}
    hits = [r for r in rels.values() if {r.from_, r.to} == {a, b}]
    for r in hits:
        if r.type in want and (r.type == "spouseOf" or r.from_ == a):
            return "found", f"{r.type}, tier {r.tier}, {r.status}"
    if hits:
        return "different", ", ".join(f"{r.type} ({r.tier})" for r in hits)
    return "missing", ""


def write_reports(stories, qmap, memberships, admitted, kinds, names, rels, events, presentation, gap_report,
                  unresolved, store):
    REPORTS.mkdir(parents=True, exist_ok=True)
    rel_by_id = {r.id: r for r in rels}
    by_story = defaultdict(list)
    for m in memberships:
        by_story[m.story].append(m)
    member_sets = {sid: {m.ref for m in ms if m.role != "candidate"} for sid, ms in by_story.items()}
    loc = {p["ref"]: p["location"] for p in presentation}
    summary_rows = []
    for st in stories:
        sid = st["id"]
        ms = by_story[sid]
        mem = member_sets[sid]
        srels = [r for r in rels if r.from_ in mem and r.to in mem]
        pub = [r for r in srels if r.status == "published"]
        L = [f"# Pilot report — {st['title']}", "",
             f"> Generated by `pipeline/pilot/build.py` on {date.today().isoformat()} (spec v1.0-draft). "
             "Question: " + " ".join(st["question"].split()), ""]
        # metrics
        anchors = [m.ref for m in ms if m.role == "anchor"]
        explained = [a for a in anchors if any(a in (r.from_, r.to) and (r.statements or r.sources) for r in pub)]
        persons = [q for q in mem if kinds.get(q) == "person"]
        linked_p = [q for q in persons if any(q in (r.from_, r.to) and kinds.get(r.to if r.from_ == q else r.from_)
                                              in ("event", "office", "institution", "work") for r in pub)]
        cross = [r for r in pub if kinds.get(r.from_) != kinds.get(r.to)]
        with_time = [r for r in pub if r.time or r.kind in ("participation",)]
        unlocated = [q for q in mem if loc.get(q) in ("unknown",)]
        seed_refs = {m.ref for m in ms if m.rule == "curated seed"}
        link_reviews = [r for r in srels if r.tier in ("review", "conflict") and r.status != "rejected"
                        and r.from_ in seed_refs and r.to in seed_refs]
        grouped = defaultdict(list)   # (reason, who) → records: one editorial decision per group
        for m in ms:
            if m.review:
                grouped[(m.review, m.about)].append(m.ref)
        review = link_reviews + list(grouped)
        tiers = Counter(r.tier for r in srels)
        L += ["## Success metrics", "",
              "| Measure | Value |", "|---|---|",
              f"| Anchors with an explainable, evidenced link to another member | {len(explained)}/{len(anchors)} |",
              f"| People linked to an admitted event, office, institution or work | {len(linked_p)}/{len(persons)} |",
              f"| Published links crossing record kinds (person↔event, person↔institution…) | {len(cross)}/{len(pub)} |",
              f"| Published links with temporal context | {len(with_time)}/{len(pub)} |",
              f"| Members admitted without coordinates (fully usable in panel/timeline) | {len(unlocated)} |",
              f"| Link tiers (all links among members) | {dict(tiers)} |",
              f"| Review list size | {len(review)} |", ""]
        # memberships
        L += ["## Members by role", "", "| Role | Record | Kind | Why | Rule |", "|---|---|---|---|---|"]
        order = {"anchor": 0, "connecting": 1, "context": 2}
        for m in sorted((m for m in ms if m.role != "candidate"), key=lambda m: (order[m.role], names.get(m.ref, m.ref))):
            L.append(f"| {m.role} | {names.get(m.ref, m.ref)} ({m.ref}) | {kinds.get(m.ref)} | {m.explanation} | {m.rule} |")
        cands = [m for m in ms if m.role == "candidate"]
        L += ["", f"Candidates found but **not admitted**: {len(cands)} "
              f"({dict(Counter(kinds.get(m.ref) for m in cands))}).", ""]
        # path and exits
        L += ["## Reading path (editorial — not a historical relationship)", ""]
        for i, p in enumerate(st.get("path", []), 1):
            q = qmap.get(p["title"])
            n_links = sum(1 for r in pub if q in (r.from_, r.to))
            L.append(f"{i}. **{p['title']}** — {p['note']} *({n_links} published links)*")
        L += ["", "**Continue exploring:** " + "; ".join(f"{e['title']} — {e['note']}" for e in st.get("exits", [])), ""]
        # gaps
        for g_sid, g, path in gap_report:
            if g_sid == sid:
                a, b = qmap.get(g["from"]), qmap.get(g["to"])
                curated_cover = [r for r in rels if r.provenance == "curated" and {r.from_, r.to} == {a, b}]
                status = (" → ".join(names.get(q, q) for q in path) if path else
                          "no kinship path; **covered by a curated link**: " + curated_cover[0].explanation if curated_cover
                          else "**no path found** (stays visible as missing)")
                L += [f"**Named gap** {g['from']} ↔ {g['to']}: {status}", ""]
        # known links
        L += ["## Known-link checks (reported, not assumed)", "", "| Expected | Result | Detail |", "|---|---|---|"]
        rel_index = {r.id: r for r in rels}
        for e in st.get("expect", []):
            res, det = expect_check(e, qmap, rel_index)
            L.append(f"| {e['from']} —{e['type']}→ {e['to']} | **{res}** | {det} |")
        L.append("")
        # relationships
        L += ["## Links among members", "",
              "Checks: **L**ogic · **A**greement (both sides) · **R**eference · **C**orroboration (enwiki link graph).", "",
              "| Kind | From | Type | To | Tier | L/A/R/C | Time | Evidence | Status |", "|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(srels, key=lambda r: (r.kind, names.get(r.from_, ""), r.type)):
            c = r.checks
            lar = "/".join(str(c.get(k, "–")) for k in ("logic", "agreement", "reference", "corroboration")) if c else "curated"
            tm = " – ".join(x for x in (fmt_date(r.time.get("start")), fmt_date(r.time.get("end"))) if x)
            L.append(f"| {r.kind} | {names.get(r.from_, r.from_)} | {r.type} | {names.get(r.to, r.to)} | {r.tier} | {lar} "
                     f"| {tm} | {short_ev(r)} | {r.status} |")
        L.append("")
        # review list
        L += ["## Review list (only what the rules could not settle)", "",
              "Links: only between curated seeds. Admissions: grouped, one decision per group.", ""]
        if not review:
            L.append("_Nothing to review._")
        for r in link_reviews:
            note = r.checks.get("logicNote") or "; ".join(r.conflicts) or "no agreement, strong reference or corroboration"
            L.append(f"- **Link** `{r.id}` — {r.explanation} *({r.tier}: {note})*")
        for (reason, who), refs in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
            sample = ", ".join(names.get(q, q) for q in refs[:6]) + (f" … (+{len(refs) - 6})" if len(refs) > 6 else "")
            L.append(f"- **Admission ×{len(refs)}** — {reason} — {who}: {sample}")
        L.append("")
        (REPORTS / f"{sid}.md").write_text("\n".join(L), encoding="utf-8")
        summary_rows.append((st, len(mem), len(pub), len(review), tiers))

    # cross-story summary
    shared = sorted(set.intersection(*member_sets.values())) if len(member_sets) > 1 else []
    sids = list(member_sets)
    bridges = [r for r in rels if r.status == "published" and len(sids) > 1 and
               ((r.from_ in member_sets[sids[0]] and r.to in member_sets[sids[1]]) or
                (r.from_ in member_sets[sids[1]] and r.to in member_sets[sids[0]]))]
    S = ["# Pilot summary", "",
         f"> Generated {date.today().isoformat()}. Shared dataset: `web/public/data/pilot/`. Spec: v1.0-draft.", "",
         "| Story | Members | Published links | Review list |", "|---|---|---|---|"]
    for st, nm, npub, nrev, _ in summary_rows:
        S.append(f"| {st['title']} | {nm} | {npub} | {nrev} |")
    S += ["", "## Crossing between stories (shared records)", "",
          f"Records that are members of both stories: {len(shared)}" + (": " + ", ".join(names.get(q, q) for q in shared) if shared else ""), "",
          f"Published links bridging the two stories: {len(bridges)}", ""]
    for r in bridges[:20]:
        S.append(f"- {r.explanation} *({r.tier})*")
    S += ["", "## Build", "",
          f"- Unresolved seed titles: {unresolved or 'none'}",
          f"- Entities fetched this run: {store.fetched}; requests — wbapi {wbapi.stats['requests']}, "
          f"wdqs {wdqs.stats['requests']}, enwiki {mw_stats['requests']}",
          "- Scope honesty: these pilots test family/marriage, rulers and claims, military events, religious "
          "institutions and disputes, some architecture. They do **not** validate culture or science.", ""]
    (REPORTS / "summary.md").write_text("\n".join(S), encoding="utf-8")


if __name__ == "__main__":
    main()
