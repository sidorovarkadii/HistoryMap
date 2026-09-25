"""Milestone 1 audit — step 2: apply v0.4 rules to fetched data; write metrics, samples, ID self-test.

THROWAWAY (audit harness). Reads pipeline/cache/audit/<category>.json (from sample.py), writes:
  docs/audit/metrics.md            generated metrics for all categories
  docs/audit/sample-<category>.csv stratified sample + deliberate hard cases, for manual spot-checking

    python pipeline/audit/measure.py
"""
from __future__ import annotations

import copy
import csv
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import rules as R  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "pipeline" / "cache" / "audit"
DOCS = ROOT / "docs" / "audit"
SCOPE = yaml.safe_load((ROOT / "pipeline" / "config" / "scope.yaml").read_text(encoding="utf-8"))
STAGE = SCOPE["stages"][SCOPE["active_stage"]]
BBOX = SCOPE["bbox"]
SUBREGIONS = SCOPE["subregions"]


def _cal_date(s: str) -> tuple[int, int, int]:
    y, m, d = (int(p) for p in s.split("-"))
    return y, m, d


WIN_CAL = R.JULIAN if STAGE["calendar"] == "julian" else R.GREGORIAN
WIN_START = R.jd_cal(*_cal_date(STAGE["from"]), WIN_CAL)
WIN_END = R.jd_cal(*_cal_date(STAGE["to_exclusive"]), WIN_CAL)
STRATA = STAGE["strata"]
CATEGORY_ORDER = ["war", "life", "architecture", "culture", "religion"]

# Which Wikidata properties produce which event types, per category (v0.4 §4.1/§4.4)
EVENT_PROPS = {
    "life": {"birth": ["P569"], "death": ["P570"]},
    "architecture": {"built": ["P571"], "destroyed": ["P576"]},
    "culture": {"created": ["P571"], "published": ["P577"], "discovered": ["P575"]},
}
TYPE_LABELS = {
    "Q178561": "battle", "Q188055": "siege", "Q198": "war", "Q51645": "council", "Q111161": "synod",
    "Q10551516": "council", "Q41521": "schism", "Q160598": "heresy", "Q1827102": "religious war",
    "Q301585": "persecution", "Q177716": "pogrom",
}

POINT_RE = re.compile(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)")


@dataclass
class Event:
    id: str = ""
    entity: str = ""
    category: str = ""
    event_type: str = ""
    label: str = ""
    kind: str = "point"                  # point | span | openSpan
    status: str = "ok"
    earliest: float = math.nan           # possible interval, JD
    latest: float = math.nan
    rt: float = math.nan                 # representative time of start, JD
    precision: int = 0
    calendar: str = ""
    raw: str = ""
    alternatives: int = 0
    statements: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    loc_via: str = "none"
    lat: float | None = None
    lon: float | None = None
    region_evidence: bool = False
    subregion: str = "unlocated"
    sitelinks: int = 0
    relations: Counter = field(default_factory=Counter)
    rel_targets: dict = field(default_factory=dict)
    enwiki: str = ""
    circa: bool = False

    @property
    def in_window(self) -> bool:
        return self.earliest < WIN_END and WIN_START < self.latest

    @property
    def year(self) -> float:
        return R.epoch_t(self.rt)


# ---------------------------------------------------------------- building events


def claims_for(item: dict, props: list[str]) -> list[R.Claim]:
    out = []
    for s in item["statements"]:
        if s["prop"] not in props:
            continue
        c = R.Claim(statement=s["statement"], prop=s["prop"], raw=s["raw"], precision=s["precision"],
                    calendar=s["calendar"], rank=s["rank"], earliest_q=s.get("earliest_q"),
                    latest_q=s.get("latest_q"), circa=s.get("circa", False), ordinal=s.get("ordinal"),
                    refs=s.get("refs", 0), wdqs_converted=s.get("wdqs_converted", True),
                    earliest_cal=s.get("earliest_cal", R.GREGORIAN), latest_cal=s.get("latest_cal", R.GREGORIAN))
        R.compute_bounds(c)
        out.append(c)
    return out


def _apply(ev: Event, res: R.Resolution, claims: list[R.Claim]) -> None:
    ev.status = res.status if res.status != "unusable" else "unusable"
    ev.alternatives = res.alternatives
    ev.statements += [c.statement for c in claims]
    for c in claims:
        ev.flags += c.flags
        ev.circa = ev.circa or c.circa
    if res.distinct_evidence:
        ev.flags.append("ordinal-qualifier")
    src = res.chosen or (claims[0] if claims else None)
    if src:
        ev.precision, ev.calendar, ev.raw = src.precision, src.calendar, src.raw


def build_span_events(qid: str, item: dict, cat: str) -> list[Event]:
    """war / religion: point (P585), span (P580+P582), openSpan (P580 only / P571 only)."""
    ev = Event(entity=qid, category=cat)
    types = [TYPE_LABELS[t] for t in item.get("matched_types", []) if t in TYPE_LABELS]
    ev.event_type = types[0] if types else cat
    start = claims_for(item, ["P580"])
    end = claims_for(item, ["P582"])
    point = claims_for(item, ["P585"])
    incept = claims_for(item, ["P571"])
    if start:
        rs = R.resolve_claims(start)
        _apply(ev, rs, start)
        ev.earliest, ev.rt = rs.earliest_jd, R.rt(rs.earliest_jd, rs.latest_jd)
        if end:
            re_ = R.resolve_claims(end)
            ev.statements += [c.statement for c in end]
            ev.kind = "span"
            ev.latest = re_.latest_jd
            if re_.status == "needsReview":
                ev.status = "needsReview"
        else:
            ev.kind = "openSpan"
            ev.latest = rs.latest_jd
        if point:
            rp = R.resolve_claims(point)
            ev.statements += [c.statement for c in point]
            ev.flags.append("point-and-span")
            if rp.status == "ok" and not (rp.earliest_jd < ev.latest and ev.earliest < rp.latest_jd):
                ev.status = "needsReview"
                ev.flags.append("point-vs-span-conflict")
    elif point:
        rp = R.resolve_claims(point)
        _apply(ev, rp, point)
        ev.kind = "point"
        ev.earliest, ev.latest = rp.earliest_jd, rp.latest_jd
        ev.rt = R.rt(ev.earliest, ev.latest)
        if end:
            ev.flags.append("point-plus-end-only")
    elif incept:
        ri = R.resolve_claims(incept)
        _apply(ev, ri, incept)
        ev.kind = "openSpan"
        ev.earliest, ev.latest = ri.earliest_jd, ri.latest_jd
        ev.rt = R.rt(ev.earliest, ev.latest)
        ev.flags.append("inception-only")
    elif end:
        re_ = R.resolve_claims(end)
        _apply(ev, re_, end)
        ev.kind = "openSpan"
        ev.earliest, ev.latest = re_.earliest_jd, re_.latest_jd
        ev.rt = R.rt(ev.earliest, ev.latest)
        ev.flags.append("end-only")
    else:
        return []
    return [ev]


def build_typed_events(qid: str, item: dict, cat: str) -> list[Event]:
    out = []
    for etype, props in EVENT_PROPS[cat].items():
        cl = claims_for(item, props)
        if not cl:
            continue
        res = R.resolve_claims(cl)
        ev = Event(entity=qid, category=cat, event_type=etype, kind="point")
        _apply(ev, res, cl)
        ev.earliest, ev.latest = res.earliest_jd, res.latest_jd
        ev.rt = R.rt(ev.earliest, ev.latest)
        out.append(ev)
    return out


# ---------------------------------------------------------------- locations (§4.4)


def parse_point(coord: str | None) -> tuple[float, float] | None:
    if not coord or not coord.startswith("Point("):   # non-Earth globes are prefixed with an IRI
        return None
    m = POINT_RE.match(coord)
    if not m:
        return None
    lon, lat = float(m.group(1)), float(m.group(2))
    return lat, lon


def in_bbox(lat: float, lon: float) -> bool:
    return BBOX["lat_min"] <= lat <= BBOX["lat_max"] and BBOX["lon_min"] <= lon <= BBOX["lon_max"]


def subregion_of(lat: float, lon: float) -> str:
    for name, b in SUBREGIONS.items():
        if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]:
            return name
    return "outside"


LOCATION_CHAIN = {
    ("war", None): ["P625", "P276"],
    ("religion", None): ["P625", "P276"],
    ("architecture", None): ["P625"],
    ("culture", None): ["P1071"],
    ("life", "birth"): ["P19"],
    ("life", "death"): ["P20"],
}


def locate(ev: Event, item: dict) -> None:
    chain = LOCATION_CHAIN.get((ev.category, ev.event_type)) or LOCATION_CHAIN[(ev.category, None)]
    places = sorted(item.get("places", []), key=lambda p: (p["statement"] or "", p.get("place") or ""))
    coords_on_item = [p for p in places if p["via"] == "P625" and parse_point(p["coord"])]
    if len(coords_on_item) > 1:
        ev.flags.append("multiple-P625")
    if ev.category == "culture" and coords_on_item:
        ev.flags.append("work-has-P625(likely-current-location)")
    for via in chain:
        for p in places:
            if p["via"] == via:
                pt = parse_point(p["coord"])
                if pt:
                    ev.lat, ev.lon = pt
                    ev.loc_via = via
                    ev.subregion = subregion_of(*pt) if in_bbox(*pt) else "outside"
                    return
    # unlocated: look for region evidence (a referenced place/polity/participant with coords in bbox)
    for p in places:
        if p["via"] in ("P17", "P710", "P276", "P19", "P20", "P27", "P551", "P937"):
            pt = parse_point(p["coord"])
            if pt and in_bbox(*pt):
                ev.region_evidence = True
                return


# ---------------------------------------------------------------- per-category processing


def load(cat: str) -> dict | None:
    path = CACHE / f"{cat}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def events_for(cat: str, data: dict) -> list[Event]:
    evs = []
    for qid, item in data["items"].items():
        built = build_span_events(qid, item, cat) if cat in ("war", "religion") else build_typed_events(qid, item, cat)
        for ev in built:
            ev.label = item.get("label") or qid
            ev.sitelinks = item.get("sitelinks", 0)
            ev.enwiki = item.get("enwiki", "")
            for r in item.get("relations", []):
                ev.relations[r["rel"]] += 1
                ev.rel_targets.setdefault(r["rel"], []).append(r["target"])
            locate(ev, item)
            evs.append(ev)
    ids, _ = R.assign_ids([(e.entity, e.event_type, e.statements) for e in evs], {})
    for e, i in zip(evs, ids):
        e.id = i
    return evs


def retained(ev: Event) -> tuple[bool, str]:
    """Scope policy §5.1 → (kept, reason)."""
    if ev.status == "unusable" or math.isnan(ev.earliest):
        return False, "date-unusable"
    if not ev.in_window:
        return False, "out-of-window"
    if ev.lat is not None:
        return (True, "located") if in_bbox(ev.lat, ev.lon) else (False, "outside-bbox")
    return (True, "unlocated-with-region-evidence") if ev.region_evidence else (False, "unlocated-no-region-evidence")


def stratum_of(ev: Event) -> str:
    y = ev.year
    for a, b in STRATA:
        if a <= y < b:
            return f"{a}-{b - 1}"
    return "edge" if ev.in_window else "outside"


def pct(n: int, d: int) -> str:
    return f"{(100 * n / d):.0f}%" if d else "–"


# ---------------------------------------------------------------- stable-ID self-test (§4.2)


def id_selftest(evs: list[Event]) -> list[str]:
    rnd = random.Random(7)
    base = [(e.entity, e.event_type, list(e.statements)) for e in evs if e.statements]
    registry: dict = {}
    ids0, _ = R.assign_ids(base, registry)
    ref = dict(zip([(a, b) for a, b, _ in base], ids0))
    results = []

    def check(name: str, events, expect_missing: set | None = None):
        reg = copy.deepcopy(registry)
        ids, missing = R.assign_ids(events, reg)
        got = dict(zip([(a, b) for a, b, _ in events], ids))
        same = all(got[k] == ref[k] for k in got)
        ok = same and (expect_missing is None or set(missing) == expect_missing)
        results.append(f"{'PASS' if ok else 'FAIL'} — {name}" + ("" if ok else f" (same={same}, missing={len(missing)})"))

    shuffled = base[:]
    rnd.shuffle(shuffled)
    check("shuffled event order", shuffled)
    check("reversed statement order", [(a, b, list(reversed(s))) for a, b, s in base])
    check("extra alternative claim added to every event", [(a, b, s + [f"{a}-FAKE-{i}"]) for i, (a, b, s) in enumerate(base)])
    multi = [(a, b, s[1:] if len(s) > 1 else s) for a, b, s in base]
    check("one statement dropped from multi-statement events", multi)
    drop = set(rnd.sample(range(len(base)), min(5, len(base))))
    kept = [x for i, x in enumerate(base) if i not in drop]
    check("5 events lose all statements → sourceMissing", kept, {ref[(base[i][0], base[i][1])] for i in drop})
    return results


# ---------------------------------------------------------------- report


def category_report(cat: str, data: dict, evs: list[Event]) -> tuple[list[str], list[Event], dict]:
    lines: list[str] = []
    decisions = [(e, *retained(e)) for e in evs]
    keep = [e for e, k, _ in decisions if k]
    excl = Counter(r for _, k, r in decisions if not k)
    kept_reason = Counter(r for _, k, r in decisions if k)
    scale = data["candidates_total"] / max(1, data.get("sampled_total", data["detailed_total"]))
    n = len(keep)

    lines += [f"## {cat}", ""]
    lines += [f"- Discovered with a stored date {data['discovery_years'][0]}–{data['discovery_years'][1]}: "
              f"{data.get('discovered_total', '?')}; plus **{data.get('straddling_spans', 0)} spans straddling the window** "
              f"(no stored value near it) → **{data['candidates_total']}** candidates",
              f"- Full date records re-fetched for {data.get('sampled_total', data['detailed_total'])}"
              + (" (seeded random subset — counts below are extrapolated ×{:.1f})".format(scale) if data["detail_sampled"] else "")
              + f"; {data['detailed_total']} still overlap the window on complete dates",
              f"- Events built: {len(evs)} → **retained in window + region: {n}**"
              + (f" (≈ {round(n * scale)} extrapolated)" if data["detail_sampled"] else ""),
              f"- Retained by type: " + ", ".join(f"{k} {v}" for k, v in Counter(e.event_type for e in keep).most_common()),
              f"- Exclusions: " + (", ".join(f"{k} {v}" for k, v in excl.most_common()) or "none"), ""]

    sl = [e.sitelinks for e in keep]
    lines += ["**Volume guard (sitelinks, retained events)**", "",
              "| ≥1 | ≥3 | ≥5 | ≥10 | ≥20 | ≥40 |", "|---|---|---|---|---|---|",
              "| " + " | ".join(str(round(sum(1 for s in sl if s >= t) * scale)) for t in (1, 3, 5, 10, 20, 40)) + " |", ""]

    prec = Counter(R.PRECISION_NAMES.get(e.precision, str(e.precision)) for e in keep)
    flags = Counter(f for e in keep for f in set(e.flags))
    lines += ["**Dates**", "",
              "| metric | value |", "|---|---|",
              "| precision | " + ", ".join(f"{k} {pct(v, n)}" for k, v in prec.most_common()) + " |",
              f"| Julian calendar model | {pct(sum(1 for e in keep if e.calendar == R.JULIAN), n)} |",
              f"| temporal kind | " + ", ".join(f"{k} {v}" for k, v in Counter(e.kind for e in keep).most_common()) + " |",
              f"| multiple claims (alternatives > 1) | {pct(sum(1 for e in keep if e.alternatives > 1), n)} |",
              f"| **needsReview (conflicting claims)** | {sum(1 for e in keep if e.status == 'needsReview')} ({pct(sum(1 for e in keep if e.status == 'needsReview'), n)}) |",
              f"| circa (P1480) | {pct(sum(1 for e in keep if e.circa), n)} |",
              f"| earliest/latest qualifiers | {pct(sum(1 for e in keep if 'earliest-qualifier' in e.flags or 'latest-qualifier' in e.flags), n)} |",
              f"| P1545 ordinal (distinct-occurrence evidence) | {flags.get('ordinal-qualifier', 0)} |",
              f"| century value ending in 00 (ambiguous) | {flags.get('century-year-ends-00', 0)} |",
              f"| point + span both recorded | {flags.get('point-and-span', 0)} (conflicting: {flags.get('point-vs-span-conflict', 0)}) |",
              ""]

    via = Counter(e.loc_via for e in keep)
    lines += ["**Locations**", "",
              "| metric | value |", "|---|---|",
              "| location source | " + ", ".join(f"{k} {pct(v, n)}" for k, v in via.most_common()) + " |",
              f"| unlocated but retained (region evidence) | {kept_reason.get('unlocated-with-region-evidence', 0)} |",
              f"| unlocated, excluded (no region evidence) | {excl.get('unlocated-no-region-evidence', 0)} |",
              f"| multiple P625 on item | {flags.get('multiple-P625', 0)} |"]
    if cat == "culture":
        lines.append(f"| work has P625 (usually *current* location — not used) | {flags.get('work-has-P625(likely-current-location)', 0)} |")
    lines.append("")

    rel_names = {"P361": "part of", "P155": "follows", "P156": "followed by", "P710": "participant",
                 "P50": "author", "P170": "creator", "P61": "discoverer", "P793": "significant event", "P1344": "participant in"}
    groups = Counter(t for e in keep for t in e.rel_targets.get("P361", []))
    big = groups.most_common(3)
    lines += ["**Relationships (retained events)**", "",
              "| property | share with ≥1 |", "|---|---|"]
    for p, name in rel_names.items():
        c = sum(1 for e in keep if e.relations.get(p))
        if c:
            lines.append(f"| {p} {name} | {pct(c, n)} |")
    lines += [f"| **no relationship at all** | {pct(sum(1 for e in keep if not e.relations), n)} |",
              f"| P361 groups among retained | {len(groups)} groups; mean {sum(groups.values()) / max(1, len(groups)):.1f} members; largest: "
              + ", ".join(f"{g} ({c})" for g, c in big) + " |", ""]

    dup = defaultdict(list)
    for e in keep:
        dup[(re.sub(r"\W+", " ", e.label.casefold()).strip(), e.event_type)].append(e)
    dups = [v for v in dup.values() if len({x.entity for x in v}) > 1 and any(
        a.earliest < b.latest and b.earliest < a.latest for i, a in enumerate(v) for b in v[i + 1:] if a.entity != b.entity)]
    lines += [f"**Possible duplicates** (same label + type, overlapping intervals, different QIDs): {len(dups)}"
              + ("; e.g. " + "; ".join(" / ".join(f"{x.label} ({x.entity})" for x in d[:2]) for d in dups[:3]) if dups else ""), ""]

    cells = Counter((stratum_of(e), e.subregion) for e in keep)
    cols = list(SUBREGIONS) + ["unlocated"]
    rows = [f"{a}-{b - 1}" for a, b in STRATA]
    lines += ["**Coverage: time stratum × subregion (retained events)**", "",
              "| stratum | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for r_ in rows:
        lines.append(f"| {r_} | " + " | ".join(str(cells.get((r_, c), 0)) for c in cols) + " |")
    lines.append("")
    stats = {"retained": n, "retained_extrapolated": round(n * scale), "scale": scale,
             "needs_review": sum(1 for e in keep if e.status == "needsReview"),
             "located": sum(1 for e in keep if e.lat is not None),
             "sl10": round(sum(1 for s in sl if s >= 10) * scale), "sl20": round(sum(1 for s in sl if s >= 20) * scale),
             "no_rel": sum(1 for e in keep if not e.relations), "sub_day": sum(1 for e in keep if e.precision < 9)}
    return lines, keep, stats


def write_sample(cat: str, keep: list[Event]) -> int:
    rnd = random.Random(42)
    cells = defaultdict(list)
    for e in keep:
        cells[(stratum_of(e), e.subregion)].append(e)
    chosen: dict[str, tuple[Event, str]] = {}
    for key in sorted(cells):
        for e in rnd.sample(cells[key], min(2, len(cells[key]))):
            chosen[e.id] = (e, "stratified")
    hard = {
        "hard:unlocated": [e for e in keep if e.lat is None],
        "hard:coarse-date": [e for e in keep if e.precision < 9],
        "hard:multi-claim": [e for e in keep if e.alternatives > 1],
        "hard:no-relations": [e for e in keep if not e.relations],
        "hard:needsReview": [e for e in keep if e.status == "needsReview"],
    }
    for why, pool in hard.items():
        pool = sorted([e for e in pool if e.id not in chosen], key=lambda e: e.id)
        for e in rnd.sample(pool, min(3, len(pool))):
            chosen[e.id] = (e, why)
    path = DOCS / f"sample-{cat}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pick", "event_id", "label", "event_type", "kind", "status", "raw_date", "precision", "calendar",
                    "rt_year", "possible_from", "possible_to", "alternatives", "loc_via", "lat", "lon", "subregion",
                    "region_evidence", "sitelinks", "relations", "flags", "wikidata", "enwiki"])
        for e, why in sorted(chosen.values(), key=lambda x: (x[1], x[0].year)):
            w.writerow([why, e.id, e.label, e.event_type, e.kind, e.status, e.raw,
                        R.PRECISION_NAMES.get(e.precision, e.precision), "julian" if e.calendar == R.JULIAN else "gregorian",
                        f"{e.year:.1f}", f"{R.epoch_t(e.earliest):.1f}", f"{R.epoch_t(e.latest):.1f}", e.alternatives,
                        e.loc_via, e.lat or "", e.lon or "", e.subregion, e.region_evidence, e.sitelinks,
                        " ".join(f"{k}:{v}" for k, v in sorted(e.relations.items())), " ".join(sorted(set(e.flags))),
                        f"https://www.wikidata.org/wiki/{e.entity}", e.enwiki])
    return len(chosen)


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    out = ["# Milestone 1 — audit metrics (generated)", "",
           f"> Generated by `pipeline/audit/measure.py`. Stage `{SCOPE['active_stage']}`: window "
           f"{STAGE['from']} → {STAGE['to_exclusive']} (exclusive), {STAGE['calendar']} calendar; bbox {BBOX}.",
           "> Rules applied: v0.4 §4.2 (claims), §4.3 (dates, JD), §4.4 (locations), §5.1 (scope).", ""]
    insert_at = len(out)
    summary, entity_cats, selftests = [], defaultdict(set), {}
    for cat in CATEGORY_ORDER:
        data = load(cat)
        if not data:
            out += [f"## {cat}", "", "_not fetched_", ""]
            continue
        evs = events_for(cat, data)
        lines, keep, st = category_report(cat, data, evs)
        ns = write_sample(cat, keep)
        lines.append(f"Sample for spot-checking: `docs/audit/sample-{cat}.csv` ({ns} rows).")
        lines.append("")
        out += lines
        selftests[cat] = id_selftest(evs)
        summary.append((cat, st))
        for e in keep:
            entity_cats[e.entity].add(cat)

    multi = Counter(tuple(sorted(c)) for c in entity_cats.values() if len(c) > 1)
    head = ["## Summary", "", "| category | retained | ≈ extrapolated | sitelinks ≥10 | ≥20 | located | coarser than year | needsReview | no relations |",
            "|---|---|---|---|---|---|---|---|---|"]
    for cat, st in summary:
        n = st["retained"]
        head.append(f"| {cat} | {n} | {st['retained_extrapolated']} | {st['sl10']} | {st['sl20']} | {pct(st['located'], n)} | "
                    f"{pct(st['sub_day'], n)} | {st['needs_review']} | {pct(st['no_rel'], n)} |")
    head += ["", "**Entities in more than one category** (supports `categories[]`): "
             + (", ".join(f"{'+'.join(k)} {v}" for k, v in multi.most_common()) or "none"), ""]
    head += ["**Stable-ID self-test** (§4.2, run on real statements)", ""]
    for cat, res in selftests.items():
        head += [f"- {cat}: " + "; ".join(res)]
    head.append("")
    out[insert_at:insert_at] = head
    (DOCS / "metrics.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(head))
    print(f"wrote {DOCS / 'metrics.md'}")


if __name__ == "__main__":
    main()
