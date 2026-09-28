"""Relationship extraction with the v1.0 semantics (spec §5.2–§5.4).

Every statement becomes an *assertion* (from, type, to, statement evidence). Assertions about the same link —
from either side, or both directions of an inverse pair — merge into ONE displayed relationship that keeps
every supporting statement and any conflicting dates.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from common import hist_date, snak_item, snak_time

# property → (kind, type, direction). direction "forward": statement subject = from; "reverse": target = from.
SPEC: dict[str, tuple[str, str, str]] = {
    "P22": ("kinship", "fatherOf", "reverse"),       # on the child: target is the father
    "P25": ("kinship", "motherOf", "reverse"),       # on the child: target is the mother
    "P40": ("kinship", "parentOf", "forward"),       # on the parent: does NOT say father or mother
    "P1290": ("kinship", "godparentOf", "reverse"),  # on the godchild
    "P3373": ("kinship", "siblingOf", "symmetric"),
    "P26": ("marriage", "spouseOf", "symmetric"),
    "P53": ("dynasty", "memberOfDynasty", "forward"),
    "P39": ("office", "heldOffice", "forward"),
    "P607": ("participation", "participatedIn", "forward"),
    "P1344": ("participation", "participatedIn", "forward"),
    "P710": ("participation", "participatedIn", "reverse"),   # on the event: target is the participant
    "P463": ("affiliation", "memberOf", "forward"),
    "P611": ("affiliation", "religiousOrder", "forward"),
    "P112": ("founding", "founded", "reverse"),      # on the institution: target is the founder
    "P88": ("founding", "commissioned", "reverse"),
    "P84": ("founding", "architectOf", "reverse"),
    "P50": ("authorship", "authorOf", "reverse"),    # on the work
    "P170": ("authorship", "creatorOf", "reverse"),
    "P61": ("authorship", "discovererOf", "reverse"),
    "P800": ("authorship", "notableWork", "forward"),  # candidate discovery only (§5.2)
    "P361": ("structure", "partOf", "forward"),
    "P156": ("structure", "precedes", "forward"),    # "followed by": subject precedes target
    "P155": ("structure", "precedes", "reverse"),    # "follows": target precedes subject
}
PROPS = list(SPEC)
# Properties worth querying in reverse (statements held by the OTHER endpoint).
REVERSE_PROPS = ["P22", "P25", "P40", "P26", "P3373", "P1290", "P607", "P1344", "P710", "P112", "P88", "P84",
                 "P50", "P170", "P61", "P361"]
KIN_PROPS = ["P22", "P25", "P40", "P26", "P3373"]   # used for second-step gap search only

# Types that name the same underlying link; the most specific survives in the displayed record.
GROUP = {"fatherOf": "parent", "motherOf": "parent", "parentOf": "parent"}
SPECIFICITY = {"parentOf": 0, "fatherOf": 1, "motherOf": 1}

REF_STRONG = {"P248", "P854"}   # stated in / reference URL
REF_WEAK = {"P143", "P4656"}    # imported from Wikimedia project / Wikimedia import URL


def parse_reference(ref: dict) -> dict:
    snaks = ref.get("snaks", {})
    props = set(snaks)
    out = {"strength": "strong" if props & REF_STRONG else "weak" if props & REF_WEAK else "none"}
    if "P248" in snaks:
        out["statedIn"] = snak_item(snaks["P248"][0])
    if "P854" in snaks:
        v = snaks["P854"][0].get("datavalue", {}).get("value")
        if v:
            out["url"] = v
    if "P143" in snaks:
        out["importedFrom"] = snak_item(snaks["P143"][0])
    if "P813" in snaks:
        t = snak_time(snaks["P813"][0])
        if t:
            out["retrieved"] = t["time"][1:11]
    return out


@dataclass
class Assertion:
    from_: str
    type: str
    to: str
    kind: str
    statement: dict


@dataclass
class Relationship:
    id: str
    kind: str
    type: str
    from_: str
    to: str
    layer: str = "relationship"
    provenance: str = "imported"
    statements: list[dict] = field(default_factory=list)
    qualifiers: dict = field(default_factory=dict)
    time: dict = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    explanation: str = ""
    uncertainty: str = ""
    sources: list[str] = field(default_factory=list)
    tier: str = ""
    checks: dict = field(default_factory=dict)
    status: str = "candidate"
    overlap: str = "unknown"

    def to_json(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v not in ("", [], {}, None)}
        d["from"] = d.pop("from_")
        return d


def extract(ent: dict) -> list[Assertion]:
    """All relationship assertions held in one entity's statements."""
    subject = ent["id"]
    out = []
    for prop, (kind, typ, direction) in SPEC.items():
        for s in ent.get("claims", {}).get(prop, []):
            if s.get("rank") == "deprecated":
                continue
            target = snak_item(s["mainsnak"])
            if not target or target == subject:
                continue
            q = s.get("qualifiers", {})
            stmt = {"entity": subject, "property": prop, "statementId": s["id"],
                    "revision": ent.get("lastrevid"), "rank": s.get("rank", "normal"),
                    "references": [parse_reference(r) for r in s.get("references", [])]}
            start = hist_date(snak_time(q["P580"][0]), s["id"]) if q.get("P580") else None
            end = hist_date(snak_time(q["P582"][0]), s["id"]) if q.get("P582") else None
            if start or end:
                stmt["time"] = {k: v for k, v in (("start", start), ("end", end)) if v}
            quals = {}
            if q.get("P2842"):
                quals["placeOfMarriage"] = snak_item(q["P2842"][0])
            if q.get("P1365"):
                quals["replaces"] = snak_item(q["P1365"][0])
            if q.get("P1366"):
                quals["replacedBy"] = snak_item(q["P1366"][0])
            if quals:
                stmt["qualifiers"] = {k: v for k, v in quals.items() if v}
            if direction == "reverse":
                a, b = target, subject
            else:
                a, b = subject, target
            if direction == "symmetric":
                a, b = sorted((subject, target))
            out.append(Assertion(a, typ, b, kind, stmt))
    return out


def rel_id(from_: str, typ: str, to: str) -> str:
    return f"{from_}>{GROUP.get(typ, typ)}>{to}"


def merge(assertions: list[Assertion]) -> dict[str, Relationship]:
    """One displayed relationship per (from, type group, to); keeps every statement and date conflict (§5.3)."""
    rels: dict[str, Relationship] = {}
    for a in assertions:
        rid = rel_id(a.from_, a.type, a.to)
        r = rels.get(rid)
        if r is None:
            r = rels[rid] = Relationship(rid, a.kind, a.type, a.from_, a.to)
        elif SPECIFICITY.get(a.type, 0) > SPECIFICITY.get(r.type, 0):
            r.type = a.type
        if not any(s["statementId"] == a.statement["statementId"] for s in r.statements):
            r.statements.append(a.statement)
        for k, v in a.statement.get("qualifiers", {}).items():
            r.qualifiers.setdefault(k, v)
    for r in rels.values():
        _merge_time(r)
    # P800 is discovery only: when an authorship statement confirms the same pair, fold it in.
    for rid, r in list(rels.items()):
        if r.type == "notableWork":
            for t in ("authorOf", "creatorOf", "discovererOf"):
                confirmed = rels.get(rel_id(r.from_, t, r.to))
                if confirmed:
                    confirmed.statements.extend(r.statements)
                    del rels[rid]
                    break
    return rels


def _merge_time(r: Relationship) -> None:
    if r.kind == "office":
        # Several P39 statements for one office are separate tenures (e.g. Æthelred: 978–1013 and 1014–1016),
        # not conflicting claims: keep each period; the displayed span is their envelope.
        periods = [s["time"] for s in r.statements if s.get("time")]
        if periods:
            r.qualifiers["periods"] = periods if len(periods) > 1 else []
            starts = [p["start"] for p in periods if p.get("start")]
            ends = [p["end"] for p in periods if p.get("end")]
            if starts:
                r.time["start"] = min(starts, key=lambda d: d["earliestJd"])
            if ends:
                r.time["end"] = max(ends, key=lambda d: d["latestJd"])
            if not r.qualifiers["periods"]:
                del r.qualifiers["periods"]
        return
    starts = [s["time"]["start"] for s in r.statements if s.get("time", {}).get("start")]
    ends = [s["time"]["end"] for s in r.statements if s.get("time", {}).get("end")]
    for key, vals in (("start", starts), ("end", ends)):
        if not vals:
            continue
        r.time[key] = sorted(vals, key=lambda d: (d["latestJd"] - d["earliestJd"], d["earliestJd"]))[0]
        for i, x in enumerate(vals):
            for y in vals[i + 1:]:
                if not (x["earliestJd"] < y["latestJd"] and y["earliestJd"] < x["latestJd"]):
                    r.conflicts.append(f"{key} dates disagree between statements: {x['raw']} vs {y['raw']}")
