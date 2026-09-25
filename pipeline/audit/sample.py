"""Milestone 1 audit — step 1: discover candidates per category in the stage window, fetch details.

THROWAWAY (audit harness). Writes pipeline/cache/audit/<category>.json for measure.py.
Every remote call is cached; a re-run makes zero HTTP requests.

  discovery  → WDQS SPARQL (which items have dates near / spanning the window)
  details    → Action API wbgetentities (full statements with GUIDs, ranks, qualifiers, refs, revision)
  place coords → WDQS SPARQL (light VALUES lookup of referenced places/polities)

    python pipeline/audit/sample.py [category ...]
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import rules as R  # noqa: E402
import wbapi  # noqa: E402
import wdqs  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "pipeline" / "cache" / "audit"
SCOPE = yaml.safe_load((ROOT / "pipeline" / "config" / "scope.yaml").read_text(encoding="utf-8"))
STAGE = SCOPE["stages"][SCOPE["active_stage"]]

# Loose discovery filter on the stored value: window ± 150 years, so coarse (century/decade) values whose
# possible interval overlaps the window are not lost. Exact scope is decided later on JD bounds.
Y0 = int(STAGE["from"][:4]) - 150
Y1 = int(STAGE["to_exclusive"][:4]) + 150
DETAIL_CAP = 3000          # per category; random (seeded) subset beyond this keeps metrics unbiased
ENTITY_BATCH = 50          # wbgetentities limit
COORD_BATCH = 200

# P27 citizenship / P551 residence / P937 work location: region evidence for people (added after first life pass)
PLACE_PROPS = ["P276", "P19", "P20", "P1071", "P17", "P710", "P27", "P551", "P937"]
RELATION_PROPS = ["P361", "P155", "P156", "P710", "P50", "P170", "P61", "P793", "P1344"]

# Audit-local category definitions (verified QIDs, 2026-09-24). Production config comes later.
CATEGORIES = {
    "war": {
        "types": {"Q178561": "battle", "Q188055": "siege", "Q198": "war"},
        "props": ["P585", "P580", "P582"],
    },
    "religion": {
        "types": {"Q51645": "ecumenical council", "Q111161": "synod", "Q10551516": "church council",
                  "Q41521": "schism", "Q160598": "heresy", "Q1827102": "religious war",
                  "Q301585": "religious persecution", "Q177716": "pogrom"},
        "props": ["P585", "P580", "P582", "P571"],
    },
    "architecture": {
        "types": {"Q23413": "castle", "Q57821": "fortification", "Q2977": "cathedral", "Q16970": "church building",
                  "Q44613": "monastery", "Q160742": "abbey", "Q32815": "mosque"},
        "props": ["P571", "P576"],
    },
    "culture": {
        # Direct P31 only: the P279* walk under "literary work" times out on WDQS regardless of window.
        # Types verified 2026-09-25 against known 901–1099 works (Book of Optics, Bayeux Tapestry, Gero Cross…).
        "types": {"Q7725634": "literary work", "Q47461344": "written work", "Q87167": "manuscript",
                  "Q48498": "illuminated manuscript", "Q690851": "Gospel Book", "Q37484": "epic poem",
                  "Q185363": "chronicle", "Q384515": "treatise", "Q3305213": "painting",
                  "Q860861": "sculpture", "Q245117": "relief sculpture", "Q838948": "work of art",
                  "Q28966302": "embroidery", "Q12579633": "invention", "Q12772819": "discovery"},
        "props": ["P571", "P577", "P575"],
        "direct_type": True,
    },
    "life": {
        "types": {"Q5": "human"},
        "props": ["P569", "P570"],
        "direct_type": True,     # wdt:P31 only (no subclass walk over 12M humans)
    },
}

DISCOVERY = """
SELECT ?item ?prop ?st ?t ?prec ?cal ?rank ?earliest ?latest ?circa ?ord ?ref WHERE {{
  {type_clause}
  VALUES (?prop ?psv) {{ {prop_values} }}
  ?item ?prop ?st .
  ?st ?psv ?v ; wikibase:rank ?rank .
  FILTER(?rank != wikibase:DeprecatedRank)
  ?v wikibase:timeValue ?t ; wikibase:timePrecision ?prec ; wikibase:timeCalendarModel ?cal .
  FILTER(?t >= "{y0:04d}-01-01T00:00:00Z"^^xsd:dateTime && ?t < "{y1:04d}-01-01T00:00:00Z"^^xsd:dateTime)
  OPTIONAL {{ ?st pq:P1319 ?earliest }}
  OPTIONAL {{ ?st pq:P1326 ?latest }}
  OPTIONAL {{ ?st pq:P1480 ?circa }}
  OPTIONAL {{ ?st pq:P1545 ?ord }}
  OPTIONAL {{ ?st prov:wasDerivedFrom ?ref }}
}}"""

# Spans that straddle the whole window (e.g. Reconquista 718–1492) have no stored value near it,
# so they need their own discovery: start before window end AND end after window start.
SPAN_DISCOVERY = """
SELECT DISTINCT ?item WHERE {{
  {type_clause}
  ?item wdt:P580 ?s ; wdt:P582 ?e .
  FILTER(?s < "{end}-01-01T00:00:00Z"^^xsd:dateTime && ?e >= "{start}-01-01T00:00:00Z"^^xsd:dateTime)
}}"""

PLACE_COORDS = """
SELECT ?place ?coord WHERE {{
  VALUES ?place {{ {items} }}
  ?place wdt:P625 ?coord .
}}"""


# ---------------------------------------------------------------- discovery (SPARQL)


def type_clause(cat: dict, type_qid: str) -> str:
    if cat.get("direct_type"):
        return f"?item wdt:P31 wd:{type_qid} ."
    return f"?item wdt:P31/wdt:P279* wd:{type_qid} ."


def discover(name: str, cat: dict) -> dict[str, dict]:
    """{item: {"statements": [...], "matched_types": [...]}} from stored values near the window (WDQS form)."""
    items: dict[str, dict[str, dict]] = {}
    item_types: dict[str, set[str]] = {}
    for tq, tlabel in cat["types"].items():
        for prop in cat["props"]:
            # One query per (type, property) keeps each query small enough for the 60 s limit.
            windows = [(Y0, Y1)] if name != "life" else [(y, min(y + 50, Y1)) for y in range(Y0, Y1, 50)]
            for (a, b) in windows:
                t0 = time.monotonic()
                rows = discovery_rows(cat, tq, prop, a, b)
                print(f"  {name:<12} {tlabel:<22} {prop:<6} {a}-{b}: {len(rows):>6} rows ({time.monotonic()-t0:.1f}s)")
                for r in rows:
                    item, st = wdqs.qid(r["item"]), wdqs.qid(r["st"])
                    items.setdefault(item, {}).setdefault(st, {
                        "statement": st, "prop": prop, "raw": r["t"], "precision": int(r["prec"]),
                        "calendar": wdqs.qid(r["cal"]), "rank": wdqs.qid(r["rank"]).split("#")[-1],
                        "earliest_q": r.get("earliest"), "latest_q": r.get("latest"), "wdqs_converted": True})
                    item_types.setdefault(item, set()).add(tq)
    return {item: {"statements": list(stmts.values()), "matched_types": sorted(item_types[item])}
            for item, stmts in items.items()}


def discovery_rows(cat: dict, tq: str, prop: str, a: int, b: int) -> list[dict]:
    """One discovery query; on repeated server timeouts split the year window in half (§5.2)."""
    q = DISCOVERY.format(type_clause=type_clause(cat, tq), prop_values=f"(p:{prop} psv:{prop})", y0=a, y1=b)
    try:
        return wdqs.query(q, retries=3)
    except RuntimeError:
        if b - a <= 10:
            raise
        mid = (a + b) // 2
        print(f"    ↳ splitting window {a}-{b}")
        return discovery_rows(cat, tq, prop, a, mid) + discovery_rows(cat, tq, prop, mid, b)


def discover_spans(name: str, cat: dict) -> dict[str, list[str]]:
    """{item: [matched type QIDs]} for spans overlapping the window (only categories with P580/P582)."""
    if "P580" not in cat["props"]:
        return {}
    out: dict[str, set[str]] = {}
    start, end = STAGE["from"][:4], STAGE["to_exclusive"][:4]
    for tq, tlabel in cat["types"].items():
        rows = wdqs.query(SPAN_DISCOVERY.format(type_clause=type_clause(cat, tq), start=start, end=end))
        print(f"  {name:<12} {tlabel:<22} spans overlapping window: {len(rows)}")
        for r in rows:
            out.setdefault(wdqs.qid(r["item"]), set()).add(tq)
    return {k: sorted(v) for k, v in out.items()}


# ---------------------------------------------------------------- window check


def _jd(date: str, cal: str) -> float:
    y, m, d = (int(p) for p in date.split("-"))
    return R.jd_cal(y, m, d, R.JULIAN if cal == "julian" else R.GREGORIAN)


WIN_START, WIN_END = _jd(STAGE["from"], STAGE["calendar"]), _jd(STAGE["to_exclusive"], STAGE["calendar"])


def overlaps_window(statements: list[dict]) -> bool:
    """Envelope of all date claims (§4.3 bounds) overlaps the window — keeps spans that straddle it."""
    lo, hi = float("inf"), float("-inf")
    for s in statements:
        c = R.Claim(s["statement"], s["prop"], s["raw"], s["precision"], s["calendar"], s["rank"],
                    s.get("earliest_q"), s.get("latest_q"), wdqs_converted=s.get("wdqs_converted", True),
                    earliest_cal=s.get("earliest_cal", R.GREGORIAN), latest_cal=s.get("latest_cal", R.GREGORIAN))
        R.compute_bounds(c)
        if c.usable():
            lo, hi = min(lo, c.earliest_jd), max(hi, c.latest_jd)
    return lo < WIN_END and WIN_START < hi


# ---------------------------------------------------------------- details (entity JSON)


def batches(seq: list[str], n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _qid_of(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _snak_time(snak: dict) -> dict | None:
    if snak.get("snaktype") != "value":
        return None
    v = snak["datavalue"]["value"]
    return {"time": v["time"], "precision": v["precision"], "calendar": _qid_of(v["calendarmodel"])}


def _snak_item(snak: dict) -> str | None:
    if snak.get("snaktype") != "value" or snak["datavalue"]["type"] != "wikibase-entityid":
        return None
    return snak["datavalue"]["value"]["id"]


def extract(ent: dict, date_props: list[str]) -> dict:
    """Entity JSON → the audit record (dates in source calendar, statement GUIDs, provenance fields)."""
    claims = ent.get("claims", {})
    out = {"label": ent.get("labels", {}).get("en", {}).get("value"),
           "desc": ent.get("descriptions", {}).get("en", {}).get("value"),
           "sitelinks": len(ent.get("sitelinks", {})),
           "revision": ent.get("lastrevid"),
           "types": sorted({t for s in claims.get("P31", []) if (t := _snak_item(s["mainsnak"]))}),
           "statements": [], "places": [], "relations": []}
    enwiki = ent.get("sitelinks", {}).get("enwiki")
    if enwiki:
        out["enwiki"] = "https://en.wikipedia.org/wiki/" + enwiki["title"].replace(" ", "_")
    for prop in date_props:
        for s in claims.get(prop, []):
            if s.get("rank") == "deprecated":
                continue
            tv = _snak_time(s["mainsnak"])
            if not tv:
                continue
            q = s.get("qualifiers", {})
            e = _snak_time(q["P1319"][0]) if q.get("P1319") else None
            la = _snak_time(q["P1326"][0]) if q.get("P1326") else None
            out["statements"].append({
                "statement": s["id"], "prop": prop, "raw": tv["time"], "precision": tv["precision"],
                "calendar": tv["calendar"], "rank": "PreferredRank" if s["rank"] == "preferred" else "NormalRank",
                "earliest_q": e["time"] if e else None, "earliest_cal": e["calendar"] if e else R.GREGORIAN,
                "latest_q": la["time"] if la else None, "latest_cal": la["calendar"] if la else R.GREGORIAN,
                "circa": any(_snak_item(x) == "Q5727902" for x in q.get("P1480", [])),
                "ordinal": (q["P1545"][0].get("datavalue", {}).get("value") if q.get("P1545") else None),
                "refs": len(s.get("references", [])), "wdqs_converted": False})
    for s in claims.get("P625", []):
        sn = s["mainsnak"]
        if sn.get("snaktype") != "value":
            continue
        v = sn["datavalue"]["value"]
        globe = _qid_of(v.get("globe", "Q2"))
        coord = f"Point({v['longitude']} {v['latitude']})"
        out["places"].append({"via": "P625", "statement": s["id"], "place": None,
                              "coord": coord if globe == "Q2" else f"{globe} {coord}"})
    for prop in PLACE_PROPS:
        for s in claims.get(prop, []):
            t = _snak_item(s["mainsnak"])
            if t and s.get("rank") != "deprecated":
                out["places"].append({"via": prop, "statement": s["id"], "place": t, "coord": None})
    for prop in RELATION_PROPS:
        for s in claims.get(prop, []):
            t = _snak_item(s["mainsnak"])
            if t and s.get("rank") != "deprecated":
                out["relations"].append({"rel": prop, "target": t, "statement": s["id"]})
    return out


def details(qids: list[str], cat: dict) -> dict[str, dict]:
    info: dict[str, dict] = {}
    for i, chunk in enumerate(batches(qids, ENTITY_BATCH), 1):
        ents = wbapi.get_entities(chunk)
        for q in chunk:
            ent = ents.get(q, {})
            if "missing" in ent or not ent:
                continue
            info[q] = extract(ent, cat["props"])
        if i % 10 == 0:
            print(f"    entities {i * ENTITY_BATCH}/{len(qids)} (cache hits {wbapi.stats['hits']}, requests {wbapi.stats['requests']})")
    # coordinates of referenced places / polities / participants (light SPARQL lookup)
    targets = sorted({p["place"] for d in info.values() for p in d["places"] if p["place"]})
    coords: dict[str, str] = {}
    for chunk in batches(targets, COORD_BATCH):
        for r in wdqs.query(PLACE_COORDS.format(items=" ".join(f"wd:{t}" for t in chunk))):
            coords.setdefault(wdqs.qid(r["place"]), r["coord"])
    for d in info.values():
        for p in d["places"]:
            if p["place"]:
                p["coord"] = coords.get(p["place"])
    print(f"    {len(info)} entities; {len(targets)} referenced places ({len(coords)} with coordinates)")
    return info


# ---------------------------------------------------------------- driver


def run_category(name: str, cat: dict) -> None:
    print(f"[{name}] discovery (stored values {Y0}–{Y1})")
    found = discover(name, cat)
    spans = discover_spans(name, cat)
    pre = {q for q, v in found.items() if overlaps_window(v["statements"])}
    new_spans = set(spans) - pre
    print(f"[{name}] {len(found)} discovered; {len(pre)} overlap the window; +{len(new_spans)} straddling spans")
    qids = sorted(pre | new_spans)
    sampled = qids
    if len(qids) > DETAIL_CAP:
        sampled = sorted(random.Random(42).sample(qids, DETAIL_CAP))
    det = details(sampled, cat)
    # Re-check the window on the COMPLETE date record from entity JSON (source calendar).
    items = {}
    for q, d in det.items():
        if overlaps_window(d["statements"]):
            d["matched_types"] = sorted(set(found.get(q, {}).get("matched_types", [])) | set(spans.get(q, [])))
            items[q] = d
    print(f"[{name}] {len(qids)} candidates ({len(sampled)} sampled); {len(items)} in window on full records")
    payload = {
        "category": name,
        "stage": SCOPE["active_stage"],
        "window": STAGE,
        "discovery_years": [Y0, Y1],
        "discovered_total": len(found),
        "straddling_spans": len(new_spans),
        "candidates_total": len(qids),
        "sampled_total": len(sampled),
        "detailed_total": len(items),
        "detail_sampled": len(sampled) < len(qids),
        "items": items,
    }
    (OUT / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{name}] saved")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    failed = []
    for name, cat in CATEGORIES.items():
        if only and name not in only:
            continue
        try:
            run_category(name, cat)
        except RuntimeError as exc:
            print(f"[{name}] FAILED: {exc}")
            failed.append(name)
    print(f"done — WDQS cache hits {wdqs.stats['hits']}, requests {wdqs.stats['requests']}; "
          f"wbapi cache hits {wbapi.stats['hits']}, requests {wbapi.stats['requests']}"
          + (f"; FAILED: {', '.join(failed)}" if failed else ""))


if __name__ == "__main__":
    main()
