"""Verification tiers and explanations (spec v1.0 §5.4, §10).

Four automatic checks per imported link — logical constraints, agreement between both sides, reference strength,
independent corroboration by English Wikipedia's link graph — decide the tier. The user only sees what remains
genuinely unresolved.
"""
from __future__ import annotations

from common import YEAR_DAYS, claims_date, label, year_of
from relations import Relationship

INVERSE_BACKED = {  # types whose link can be stated on both endpoints
    "fatherOf": ({"P22", "P25"}, {"P40"}), "motherOf": ({"P22", "P25"}, {"P40"}),
    "parentOf": ({"P22", "P25"}, {"P40"}), "spouseOf": ({"P26"}, {"P26"}),
    "siblingOf": ({"P3373"}, {"P3373"}), "participatedIn": ({"P607", "P1344"}, {"P710"}),
}


def lifetimes(ents: dict[str, dict], people: set[str]) -> dict[str, dict]:
    return {q: {"birth": claims_date(ents[q], "P569"), "death": claims_date(ents[q], "P570")}
            for q in people if q in ents}


def _yrs(n: float) -> float:
    return n * YEAR_DAYS


def logic(r: Relationship, life: dict, ents: dict) -> tuple[str, str]:
    """('ok' | 'fail' | 'n/a', note). Fails only when impossible under EVERY reading of the date bounds."""
    a, b = life.get(r.from_, {}), life.get(r.to, {})
    ab, ad, bb, bd = a.get("birth"), a.get("death"), b.get("birth"), b.get("death")
    t = r.type
    if t in ("fatherOf", "motherOf", "parentOf"):
        if ab and bb and ab["earliestJd"] + _yrs(12) > bb["latestJd"]:
            return "fail", "parent born less than 12 years before the child"
        if ad and bb:
            grace = 0 if t == "motherOf" else _yrs(1)
            if ad["latestJd"] + grace < bb["earliestJd"]:
                return "fail", "parent died before the child's birth"
        return ("ok", "") if (ab or ad) and bb else ("n/a", "birth dates missing")
    if t == "godparentOf":
        if ab and bb and ab["earliestJd"] > bb["latestJd"]:
            return "fail", "godparent born after the godchild"
        return ("ok", "") if ab and bb else ("n/a", "")
    if t == "spouseOf":
        if ab and bd and bb and ad:
            if not (ab["earliestJd"] < bd["latestJd"] and bb["earliestJd"] < ad["latestJd"]):
                return "fail", "lifetimes do not overlap"
        start = r.time.get("start")
        if start:
            if (ad and start["earliestJd"] > ad["latestJd"]) or (bd and start["earliestJd"] > bd["latestJd"]):
                return "fail", "marriage dated after a spouse's death"
        return ("ok", "") if (ab or ad) and (bb or bd) else ("n/a", "lifetimes missing")
    if t == "participatedIn" and r.from_ in life:
        from expand import event_interval
        iv = event_interval(ents.get(r.to))
        if iv and ab and ab["earliestJd"] > iv[1]:
            return "fail", "born after the event"
        if iv and ad and ad["latestJd"] + _yrs(1) < iv[0]:
            return "fail", "died before the event"
        return ("ok", "") if iv and (ab or ad) else ("n/a", "")
    if t == "heldOffice":
        s, e = r.time.get("start"), r.time.get("end")
        if s and ab and s["latestJd"] < ab["earliestJd"]:
            return "fail", "tenure begins before birth"
        if e and ad and e["earliestJd"] > ad["latestJd"] + _yrs(1):
            return "fail", "tenure ends after death"
        return ("ok", "") if (s or e) and (ab or ad) else ("n/a", "")
    if t in ("founded", "commissioned"):
        inc = claims_date(ents.get(r.to, {}), "P571") if r.to in ents else None
        if inc and ab and ab["earliestJd"] > inc["latestJd"]:
            return "fail", "founder born after the foundation"
        return ("ok", "") if inc and ab else ("n/a", "")
    return "n/a", ""


def agreement(r: Relationship) -> str:
    sides = INVERSE_BACKED.get(r.type)
    if not sides:
        return "n/a"
    holders = {s["entity"] for s in r.statements}
    return "both" if {r.from_, r.to} <= holders else "one-sided"


def reference_strength(r: Relationship) -> str:
    best = "none"
    for s in r.statements:
        for ref in s.get("references", []):
            if ref["strength"] == "strong":
                return "strong"
            if ref["strength"] == "weak":
                best = "weak"
    return best


def corroboration(r: Relationship, links: dict[str, set[str]]) -> str:
    la, lb = links.get(r.from_), links.get(r.to)
    if la is None and lb is None:
        return "n/a"
    return "yes" if (la and r.to in la) or (lb and r.from_ in lb) else "no"


def tier_of(checks: dict, r: Relationship) -> str:
    if checks["logic"] == "fail" or r.conflicts:
        return "conflict"
    if r.type == "notableWork":
        return "review"
    agree = checks["agreement"] == "both"
    strong = checks["reference"] == "strong"
    corr = checks["corroboration"] == "yes"
    if (agree or strong) and corr:
        return "verified"
    if agree or strong or corr:
        return "supported"
    return "review"


def assess(r: Relationship, life: dict, ents: dict, links: dict[str, set[str]]) -> None:
    lg, note = logic(r, life, ents)
    r.checks = {"logic": lg, "agreement": agreement(r), "reference": reference_strength(r),
                "corroboration": corroboration(r, links)}
    if note:
        r.checks["logicNote"] = note
    r.tier = tier_of(r.checks, r)


# ---------------------------------------------------------------- explanations


def fmt_date(h: dict | None) -> str:
    if not h:
        return ""
    y = int(year_of(h["earliestJd"]) + 0.001)
    p = h["precision"]
    if p in ("day", "month", "year"):
        return h["raw"][1:5].lstrip("0") if h["raw"].startswith("+") else str(y)
    if p == "decade":
        return f"{y}s"
    if p == "century":
        c = int(year_of(h["latestJd"]) - 1) // 100 + 1
        return f"{c}{'th' if 10 <= c % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(c % 10, 'th')} century"
    return f"c. {y}"


TEMPLATES = {
    "fatherOf": "{a} was the father of {b}.",
    "motherOf": "{a} was the mother of {b}.",
    "parentOf": "{a} was a parent of {b} (the record does not say whether father or mother).",
    "siblingOf": "{a} and {b} were siblings.",
    "godparentOf": "{a} was a godparent of {b}.",
    "spouseOf": "{a} and {b} were married{when}{where}.",
    "memberOfDynasty": "{a} belonged to the {b}.",
    "heldOffice": "{a} held the office of {b}{when}.",
    "participatedIn": "{a} took part in {b}.",
    "memberOf": "{a} was a member of {b}.",
    "religiousOrder": "{a} belonged to the religious order {b}.",
    "founded": "{a} founded {b}.",
    "commissioned": "{b} was commissioned by {a}.",
    "architectOf": "{a} was an architect of {b}.",
    "authorOf": "{a} was an author of {b}.",
    "creatorOf": "{a} created {b}.",
    "discovererOf": "{a} is credited with discovering or inventing {b}.",
    "notableWork": "{b} is recorded as a notable work of {a}; the authorship role is not yet verified.",
    "partOf": "{a} was part of {b}.",
    "precedes": "{a} came before {b} in a recorded sequence.",
}


def explain(r: Relationship, names: dict[str, str], place_names: dict[str, str]) -> None:
    if r.provenance == "curated":
        return
    s, e = fmt_date(r.time.get("start")), fmt_date(r.time.get("end"))
    when = f" ({s}–{e})" if s and e else f" (from {s})" if s else f" (until {e})" if e else ""
    where = ""
    if r.qualifiers.get("placeOfMarriage"):
        where = f" at {place_names.get(r.qualifiers['placeOfMarriage'], r.qualifiers['placeOfMarriage'])}"
    periods = r.qualifiers.get("periods") or []
    if len(periods) > 1:
        spans = [" – ".join(x for x in (fmt_date(p.get("start")), fmt_date(p.get("end"))) if x) for p in periods]
        when = f" in {len(periods)} separate periods ({'; '.join(sorted(spans))})"
    text = TEMPLATES.get(r.type, "{a} is linked to {b} ({t}).").format(
        a=names.get(r.from_, r.from_), b=names.get(r.to, r.to), when=when, where=where, t=r.type)
    r.explanation = "Wikidata records: " + text
    if r.conflicts:
        r.uncertainty = "; ".join(r.conflicts)
