"""v0.4 contract rules used by the Milestone 1 audit (dates §4.3, claims §4.2, IDs §4.2).

THROWAWAY (audit harness). The production pipeline will re-implement these with tests; the audit
uses them to measure how real Wikidata records behave under the rules.
"""
from __future__ import annotations

import base64
import hashlib
import math
from dataclasses import dataclass, field

JULIAN = "Q1985786"
GREGORIAN = "Q1985727"

# ---------------------------------------------------------------- Julian Day conversion


def jd_gregorian(y: int, m: int, d: int) -> float:
    """JD at 00:00 UT of a proleptic Gregorian date (Fliegel–Van Flandern)."""
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    jdn = d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045
    return jdn - 0.5


def jd_julian(y: int, m: int, d: int) -> float:
    """JD at 00:00 UT of a proleptic Julian date."""
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    jdn = d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - 32083
    return jdn - 0.5


def jd_cal(y: int, m: int, d: int, cal: str) -> float:
    return jd_julian(y, m, d) if cal == JULIAN else jd_gregorian(y, m, d)


def epoch_t(jd: float) -> float:
    """Timeline axis (Julian epoch). Positioning only — never used for boundaries."""
    return 2000.0 + (jd - 2451545.0) / 365.25


# ---------------------------------------------------------------- HistDate


PRECISION_NAMES = {6: "millennium", 7: "century", 8: "decade", 9: "year", 10: "month", 11: "day"}


@dataclass
class Claim:
    statement: str            # wds GUID
    prop: str                 # "P585"
    raw: str                  # timeValue as returned by WDQS
    precision: int
    calendar: str             # QID of calendar model
    rank: str                 # "PreferredRank" | "NormalRank"
    earliest_q: str | None = None   # P1319
    latest_q: str | None = None     # P1326
    circa: bool = False             # P1480 = Q5727902
    ordinal: str | None = None      # P1545
    refs: int = 0
    wdqs_converted: bool = True     # True: value came from WDQS (day precision already Gregorian);
                                    # False: entity JSON (value in its source calendar at every precision)
    earliest_cal: str = GREGORIAN   # calendar of the P1319/P1326 qualifier values
    latest_cal: str = GREGORIAN
    flags: list[str] = field(default_factory=list)
    earliest_jd: float = math.nan
    latest_jd: float = math.nan     # exclusive

    def usable(self) -> bool:
        return not math.isnan(self.earliest_jd)


def _ymd(raw: str) -> tuple[int, int, int]:
    s = raw.lstrip("+")
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    date = s.split("T")[0]
    y, m, d = (int(p) for p in date.split("-"))
    return (-y if neg else y), m, d


def compute_bounds(c: Claim) -> None:
    """Fill earliest_jd / latest_jd (half-open) following §4.3 + the WDQS conversion finding.

    Entity JSON stores every value in its source calendar. WDQS converts a Julian value to Gregorian
    only at day precision (11); coarser values keep the source-calendar year (verified on Battle of
    Hastings vs First Crusade, 2026-09-24). For WDQS month precision (10) we assume unconverted (flagged).
    """
    try:
        y, m, d = _ymd(c.raw)
    except (ValueError, IndexError):
        c.flags.append("unparseable")
        return
    cal = c.calendar
    p = c.precision
    if p >= 11:
        c.earliest_jd = jd_gregorian(y, m, d) if c.wdqs_converted else jd_cal(y, m, d, cal)
        c.latest_jd = c.earliest_jd + 1
    elif p == 10:
        c.earliest_jd = jd_cal(y, max(m, 1), 1, cal)
        ny, nm = (y + 1, 1) if m >= 12 else (y, max(m, 1) + 1)
        c.latest_jd = jd_cal(ny, nm, 1, cal)
        if cal == JULIAN and c.wdqs_converted:
            c.flags.append("month-julian-assumed-unconverted")
    elif p == 9:
        c.earliest_jd, c.latest_jd = jd_cal(y, 1, 1, cal), jd_cal(y + 1, 1, 1, cal)
    elif p == 8:
        k = (y // 10) * 10
        c.earliest_jd, c.latest_jd = jd_cal(k, 1, 1, cal), jd_cal(k + 10, 1, 1, cal)
    elif p == 7:
        cent = math.ceil(y / 100)
        c.earliest_jd = jd_cal(100 * (cent - 1) + 1, 1, 1, cal)
        c.latest_jd = jd_cal(100 * cent + 1, 1, 1, cal)
        if y % 100 == 0:
            c.flags.append("century-year-ends-00")  # ambiguous per Help:Dates
    elif p == 6:
        mil = math.ceil(y / 1000)
        c.earliest_jd = jd_cal(1000 * (mil - 1) + 1, 1, 1, cal)
        c.latest_jd = jd_cal(1000 * mil + 1, 1, 1, cal)
    else:
        c.flags.append(f"precision-{p}-too-coarse")
        return
    # P1319 / P1326 qualifiers override bounds (qualifier's own calendar; day-level granularity)
    if c.earliest_q:
        try:
            ey, em, ed = _ymd(c.earliest_q)
            c.earliest_jd = jd_cal(ey, max(em, 1), max(ed, 1), c.earliest_cal)
            c.flags.append("earliest-qualifier")
        except (ValueError, IndexError):
            pass
    if c.latest_q:
        try:
            ly, lm, ld = _ymd(c.latest_q)
            c.latest_jd = jd_cal(ly, max(lm, 1), max(ld, 1), c.latest_cal) + 1
            c.flags.append("latest-qualifier")
        except (ValueError, IndexError):
            pass


def rt(earliest: float, latest: float) -> float:
    """Representative time (JD) — midpoint convention (§4.3)."""
    return (earliest + latest) / 2


# ---------------------------------------------------------------- claim resolution (§4.2)


@dataclass
class Resolution:
    chosen: Claim | None
    status: str                   # "ok" | "needsReview" | "unusable"
    alternatives: int             # number of non-deprecated usable claims considered
    earliest_jd: float = math.nan
    latest_jd: float = math.nan
    distinct_evidence: bool = False   # P1545 ordinals present → could be repeated occurrences


def _overlap(a: Claim, b: Claim) -> bool:
    return a.earliest_jd < b.latest_jd and b.earliest_jd < a.latest_jd


def resolve_claims(claims: list[Claim]) -> Resolution:
    """Alternative claims about ONE event → a single resolved date, or needsReview.

    Rule (v0.4 §4.2):
      1. Deprecated claims are already excluded by the query.
      2. Best rank = preferred claims if any, else all normal claims.
      3. If the best-rank claims are mutually overlapping → choose by refs desc, narrowest interval, statement id.
      4. If any pair of best-rank claims does not overlap → needsReview, use the envelope of all of them.
    """
    usable = [c for c in claims if c.usable()]
    if not usable:
        return Resolution(None, "unusable", 0)
    distinct = any(c.ordinal for c in usable)
    preferred = [c for c in usable if c.rank == "PreferredRank"]
    best = preferred or usable
    conflict = any(not _overlap(a, b) for i, a in enumerate(best) for b in best[i + 1:])
    if conflict:
        return Resolution(None, "needsReview", len(usable),
                          min(c.earliest_jd for c in best), max(c.latest_jd for c in best), distinct)
    chosen = sorted(best, key=lambda c: (-c.refs, c.latest_jd - c.earliest_jd, c.statement))[0]
    return Resolution(chosen, "ok", len(usable), chosen.earliest_jd, chosen.latest_jd, distinct)


# ---------------------------------------------------------------- occurrence registry (§4.2)


def _occ_key(statement_guid: str) -> str:
    digest = hashlib.sha1(statement_guid.encode("utf-8")).digest()
    return base64.b32encode(digest).decode("ascii").lower()[:5]


def assign_ids(events: list[tuple[str, str, list[str]]], registry: dict) -> tuple[list[str], list[str]]:
    """Assign stable IDs. events = [(entity, eventType, [statement GUIDs])]; registry is mutated (append-only).

    Returns (ids in input order, ids of registry entries whose statements all vanished → sourceMissing).
    """
    by_stmt = {s: eid for eid, e in registry.items() for s in e["statements"]}
    ids, seen = [], set()
    for entity, etype, stmts in events:
        match = next((by_stmt[s] for s in stmts if s in by_stmt), None)
        if match:
            eid = match
            known = set(registry[eid]["statements"])
            registry[eid]["statements"] += [s for s in stmts if s not in known]
        else:
            base = f"{entity}:{etype}"
            eid = base if base not in registry else f"{base}:{_occ_key(sorted(stmts)[0])}"
            registry[eid] = {"entity": entity, "eventType": etype, "statements": list(stmts)}
            for s in stmts:
                by_stmt[s] = eid
        ids.append(eid)
        seen.add(eid)
    current = {s for _, _, st in events for s in st}
    missing = [eid for eid, e in registry.items()
               if eid not in seen and not any(s in current for s in e["statements"])]
    return ids, missing
