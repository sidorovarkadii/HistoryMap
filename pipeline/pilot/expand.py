"""Bounded expansion and admission (spec v1.0 §3, §7, §9).

One step from the story's records, in both directions. A second step only for a named gap (kinship/marriage).
Admission is per story (a membership), by explicit rules that write their reason down.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from common import claims_date, label, overlaps, snak_item
from relations import KIN_PROPS, Relationship

# ---------------------------------------------------------------- classification

# Checked in order against the English labels of an item's P31 classes (first match wins).
KIND_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("event", ("battle", "war", "siege", "conflict", "council", "synod", "crusade", "schism", "invasion",
               "conquest", "campaign", "rebellion", "massacre", "pogrom", "controversy", "dispute", "strife",
               "coronation", "military operation", "historical event", "event", "occurrence", "raid", "penance")),
    ("office", ("position", "office", "monarchy", "ecclesiastical occupation", "papacy", "title of honor")),
    ("dynasty", ("dynasty", "noble family", "royal family", "family", "royal house", "noble house", "clan")),
    ("institution", ("abbey", "monastery", "cathedral", "church", "castle", "priory", "basilica", "mosque",
                     "palace", "building", "fortification", "religious order", "religious community", "university",
                     "school", "archdiocese", "diocese", "religious institute")),
    ("polity", ("state", "kingdom", "duchy", "county", "empire", "principality", "caliphate", "country",
                "margraviate", "realm", "polity", "sultanate", "emirate", "papal states", "march")),
    ("work", ("work", "book", "manuscript", "chronicle", "tapestry", "poem", "embroidery", "painting",
              "document", "register", "cadastre", "survey", "treatise", "letter")),
    ("movement", ("movement", "reform", "doctrine", "heresy")),
    ("place", ("city", "town", "village", "settlement", "region", "island", "commune", "municipality",
               "river", "hill", "area", "location", "site")),
]


def classify(ent: dict, class_labels: dict[str, str]) -> tuple[str, list[str]]:
    """(kind, class labels). Humans by Q5; everything else by P31 class-label keywords."""
    classes = [snak_item(s["mainsnak"]) for s in ent.get("claims", {}).get("P31", [])]
    classes = [c for c in classes if c]
    names = [class_labels.get(c, c) for c in classes]
    if "Q5" in classes:
        return "person", names
    low = [n.lower() for n in names]
    # Strong polity markers win over keyword matches ("Crusader states" must not read as an event).
    if any(n in ("historical country", "sovereign state", "country", "state", "former country") for n in low):
        return "polity", names
    for kind, words in KIND_KEYWORDS:
        if any(w in n for n in low for w in words):
            return kind, names
    return "other", names


# ---------------------------------------------------------------- activity overlap (§7.1)


def event_interval(ent: dict | None) -> tuple[float, float] | None:
    if not ent:
        return None
    start = claims_date(ent, "P580") or claims_date(ent, "P585") or claims_date(ent, "P571")
    if not start:
        return None
    end = claims_date(ent, "P582") or start
    return start["earliestJd"], end["latestJd"]


def activity_overlap(qid: str, rels: list[Relationship], ents: dict[str, dict]) -> tuple[str, list[str]]:
    """'overlapping' / 'not-overlapping' / 'unknown' from DATED activities — never from birth/death alone."""
    spans, notes = [], []
    for r in rels:
        if qid not in (r.from_, r.to):
            continue
        other = r.to if r.from_ == qid else r.from_
        if r.kind in ("office", "marriage") and r.time:
            lo = r.time.get("start", r.time.get("end"))["earliestJd"]
            hi = r.time.get("end", r.time.get("start"))["latestJd"]
            spans.append((lo, hi))
            notes.append(f"{r.type} {other}")
        elif r.kind in ("participation", "founding", "authorship"):
            iv = event_interval(ents.get(other))
            if iv:
                spans.append(iv)
                notes.append(f"{r.type} {other}")
    if not spans:
        return "unknown", notes
    return ("overlapping" if any(overlaps(lo, hi) for lo, hi in spans) else "not-overlapping"), notes


# ---------------------------------------------------------------- admission


@dataclass
class Membership:
    story: str
    ref: str
    role: str                 # anchor | connecting | context | candidate
    explanation: str
    sources: list[str] = field(default_factory=list)
    rule: str = ""            # which admission rule fired
    review: str = ""          # non-empty → appears on the review list with this reason
    about: str = ""           # the seed(s) the review item relates to (groups the review list)

    def to_json(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in ("", [], None)}


def links_between(x: str, members: set[str], rels: dict[str, Relationship]) -> list[Relationship]:
    return [r for r in rels.values() if (r.from_ == x and r.to in members) or (r.to == x and r.from_ in members)]


KIN_TYPES = {"fatherOf", "motherOf", "parentOf", "spouseOf", "siblingOf", "godparentOf"}


def kin_phrase(x: str, links: list[Relationship], names: dict[str, str]) -> str:
    """Readable family wording from x's own side: 'child of Cnut the Great, Emma of Normandy; sibling of Edward'."""
    words: dict[str, list[str]] = {}
    for r in links:
        if r.type not in KIN_TYPES:
            continue
        outward = r.from_ == x
        word = {"fatherOf": ("father of", "child of"), "motherOf": ("mother of", "child of"),
                "parentOf": ("parent of", "child of"), "godparentOf": ("godparent of", "godchild of"),
                "spouseOf": ("spouse of", "spouse of"), "siblingOf": ("sibling of", "sibling of")}[r.type][0 if outward else 1]
        other = r.to if outward else r.from_
        words.setdefault(word, []).append(names.get(other, other))
    return "; ".join(f"{w} {', '.join(sorted(set(n)))}" for w, n in words.items())


def admit(story_id: str, members: dict[str, str], candidates: set[str], kinds: dict[str, str],
          rels: dict[str, Relationship], ents: dict[str, dict], names: dict[str, str]) -> list[Membership]:
    """Apply the explicit admission rules (§7) to one story's one-step neighbourhood.

    `members` = the records admission is measured against: curated seeds (anchor/context) and named-gap
    intermediaries — NOT onward exits (exits are destinations, not starting points for expansion).
    Links to curated seeds count; "took part in the same war" alone never admits anyone.
    """
    out = []
    member_set = set(members)
    seeds = {q for q, role in members.items() if role in ("anchor", "context")}
    anchors = {q for q, role in members.items() if role == "anchor"}
    rel_list = list(rels.values())
    for x in sorted(candidates - member_set):
        links = links_between(x, member_set, rels)
        if not links:
            continue
        kind = kinds.get(x, "other")
        other = lambda r: r.to if r.from_ == x else r.from_  # noqa: E731
        linked = sorted({other(r) for r in links})
        who = ", ".join(names.get(m, m) for m in linked[:3])
        types = {r.type for r in links}
        seed_links = [r for r in links if other(r) in seeds]
        kin_seed = {r.type for r in seed_links if r.type in KIN_TYPES}
        non_participation_seeds = {other(r) for r in seed_links if r.kind != "participation"}
        role, rule, review, why = "candidate", "", "", ""

        if kind == "event":
            iv = event_interval(ents.get(x))
            in_window = iv is not None and overlaps(*iv)
            anchor_part = any(other(r) in anchors and r.type in ("participatedIn", "partOf") for r in links)
            if anchor_part and in_window:
                role, rule, why = "connecting", "R1 event with an anchor", f"involves {who}"
            elif anchor_part and iv is None:
                review, why = "event with an anchor but no usable date", f"involves {who}"
        elif kind == "person":
            state, _ = activity_overlap(x, rel_list, ents)
            if kin_seed and state == "overlapping":
                role, rule, why = "connecting", "R2a kin of a seed + active in window", kin_phrase(x, seed_links, names)
            elif len(non_participation_seeds) >= 2:
                role, rule, why = "connecting", "R2b ≥2 seeds, not participation alone", f"linked to {who}"
            elif kin_seed and state == "unknown" and (set(linked) & anchors):
                review, why = "relative of an anchor; activity dates unknown", kin_phrase(x, seed_links, names)
            elif state == "not-overlapping" and any(
                    r.type in ("fatherOf", "motherOf", "parentOf") and r.from_ == x for r in seed_links):
                # x is the PARENT of a seed and was active only outside the window → reviewed context exception
                review, why = "possible context exception (ancestor active outside window)", f"parent of {who}"
            else:
                why = f"{'/'.join(sorted(types))} link to {who}"
        elif kind == "office":
            if any(r.type == "heldOffice" and other(r) in seeds for r in links):
                role, rule, why = "context", "R3 office held by a seed", f"office held by {who}"
        elif kind == "dynasty":
            if len({other(r) for r in seed_links}) >= 2:
                role, rule, why = "context", "R4 house of ≥2 seeds", f"house of {who}"
        elif kind == "institution":
            if {"founded", "memberOf", "religiousOrder"} & {r.type for r in seed_links}:
                role, rule, why = "connecting", "R5 founded by / affiliated with a seed", f"linked to {who}"
            elif len({other(r) for r in seed_links}) >= 2:
                role, rule, why = "connecting", "R5b building linked to ≥2 seeds", f"linked to {who}"
            else:
                why = f"{'/'.join(sorted(types))} {who} (building not otherwise connected)"
        elif kind == "polity":
            if any(r.type == "participatedIn" and other(r) in anchors for r in links):
                role, rule, why = "context", "R6 polity party to an anchor event", f"party to {who}"
        elif kind == "work":
            if {"authorOf", "creatorOf", "discovererOf"} & {r.type for r in seed_links}:
                role, rule, why = "connecting", "R7 work by a seed", f"by {who}"
            elif "notableWork" in types:
                review, why = "P800 notable work only — authorship not verified", f"notable work of {who}"
        else:
            if len(non_participation_seeds) >= 2:
                role, rule, why = "connecting", "R8 other, ≥2 seeds", f"linked to {who}"
        about = ", ".join(names.get(m, m) for m in linked if m in seeds) if review else ""
        out.append(Membership(story_id, x, role, why, rule=rule, review=review, about=about))
    return out


# ---------------------------------------------------------------- second step: named gaps


def kin_neighbours(qid: str, ents: dict[str, dict], rels: dict[str, Relationship]) -> set[str]:
    out = set()
    ent = ents.get(qid, {})
    for p in KIN_PROPS:
        for s in ent.get("claims", {}).get(p, []):
            t = snak_item(s["mainsnak"])
            if t:
                out.add(t)
    for r in rels.values():
        if r.kind in ("kinship", "marriage") and qid in (r.from_, r.to):
            out.add(r.to if r.from_ == qid else r.from_)
    out.discard(qid)
    return out


def find_gap_path(a: str, b: str, store, ents: dict[str, dict], rels: dict[str, Relationship]) -> list[str] | None:
    """Shortest kinship/marriage path a … b with at most three intermediaries (a–x–z–y–b).

    Step one = each endpoint's own kin; step two = the kin of a's kin (fetched only for this named gap).
    """
    na, nb = kin_neighbours(a, ents, rels), kin_neighbours(b, ents, rels)
    ents.update(store.get(na | nb))
    na, nb = kin_neighbours(a, ents, rels), kin_neighbours(b, ents, rels)
    if b in na:
        return [a, b]
    common = sorted(na & nb)
    if common:
        return [a, common[0], b]
    for x in sorted(na):
        for y in sorted(nb):
            if y in kin_neighbours(x, ents, rels) or x in kin_neighbours(y, ents, rels):
                return [a, x, y, b]
    # second step from a's side
    second = {x: kin_neighbours(x, ents, rels) for x in sorted(na)}
    ents.update(store.get(set().union(*second.values()) if second else set()))
    for x, zs in second.items():
        for z in sorted(zs - {a}):
            if z == b:
                return [a, x, b]
            if z in nb:
                return [a, x, z, b]
            zk = kin_neighbours(z, ents, rels)
            for y in sorted(nb):
                if y in zk:
                    return [a, x, z, y, b]
    return None
