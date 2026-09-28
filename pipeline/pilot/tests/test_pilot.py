"""Unit tests for the pilot pipeline's relationship semantics, overlap states, tiers and shared identities."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True

from common import cal_jd  # noqa: E402
from crosscheck import assess, tier_of  # noqa: E402
from expand import activity_overlap  # noqa: E402
from relations import Relationship, extract, merge  # noqa: E402

JULIAN = "http://www.wikidata.org/entity/Q1985786"


def item(qid):
    return {"type": "wikibase-entityid", "value": {"id": qid}}


def claim(sid, prop, target=None, time=None, precision=9, qualifiers=None, refs=None, rank="normal"):
    if time:
        dv = {"type": "time", "value": {"time": time, "precision": precision, "calendarmodel": JULIAN}}
    else:
        dv = item(target)
    return {"id": sid, "rank": rank, "mainsnak": {"snaktype": "value", "property": prop, "datavalue": dv},
            "qualifiers": qualifiers or {}, "references": refs or []}


def entity(qid, claims, rev=1):
    by = {}
    for c in claims:
        by.setdefault(c["mainsnak"]["property"], []).append(c)
    return {"id": qid, "lastrevid": rev, "labels": {"en": {"value": qid}}, "claims": by}


def qual_time(t, precision=9):
    return {"snaktype": "value", "datavalue": {"type": "time", "value":
            {"time": t, "precision": precision, "calendarmodel": JULIAN}}}


# ---------------------------------------------------------------- semantics


def test_p40_alone_is_neutral_parent():
    rels = merge(extract(entity("Q1", [claim("Q1$a", "P40", "Q2")])))
    (r,) = rels.values()
    assert (r.from_, r.type, r.to) == ("Q1", "parentOf", "Q2")


def test_inverse_pair_merges_keeps_both_statements_and_specific_type():
    parent = entity("Q1", [claim("Q1$a", "P40", "Q2")])
    child = entity("Q2", [claim("Q2$b", "P25", "Q1")])
    rels = merge(extract(parent) + extract(child))
    assert len(rels) == 1
    (r,) = rels.values()
    assert r.type == "motherOf" and {s["statementId"] for s in r.statements} == {"Q1$a", "Q2$b"}


def test_spouse_symmetric_merges_and_keeps_place_of_marriage_and_conflicting_dates():
    a = entity("Q1", [claim("Q1$m", "P26", "Q2", qualifiers={"P580": [qual_time("+1017-00-00T00:00:00Z")],
                                                            "P2842": [{"snaktype": "value", "datavalue": item("Q9")}]})])
    b = entity("Q2", [claim("Q2$m", "P26", "Q1", qualifiers={"P580": [qual_time("+1020-00-00T00:00:00Z")]})])
    rels = merge(extract(a) + extract(b))
    (r,) = rels.values()
    assert r.type == "spouseOf" and len(r.statements) == 2
    assert r.qualifiers["placeOfMarriage"] == "Q9"
    assert r.conflicts, "differing marriage years must be kept as a conflict, not silently merged"


def test_p800_is_candidate_only_until_authorship_confirms():
    person = entity("Q1", [claim("Q1$w", "P800", "Q5")])
    rels = merge(extract(person))
    assert [r.type for r in rels.values()] == ["notableWork"]
    work = entity("Q5", [claim("Q5$a", "P50", "Q1")])
    rels = merge(extract(person) + extract(work))
    assert [r.type for r in rels.values()] == ["authorOf"]
    assert len(next(iter(rels.values())).statements) == 2


def test_two_office_statements_are_two_tenures_not_a_conflict():
    q = lambda s, e: {"P580": [qual_time(s)], "P582": [qual_time(e)]}  # noqa: E731
    king = entity("Q1", [claim("Q1$a", "P39", "QKING", qualifiers=q("+0978-00-00T00:00:00Z", "+1013-00-00T00:00:00Z")),
                         claim("Q1$b", "P39", "QKING", qualifiers=q("+1014-00-00T00:00:00Z", "+1016-00-00T00:00:00Z"))])
    (r,) = merge(extract(king)).values()
    assert not r.conflicts and len(r.qualifiers["periods"]) == 2
    assert r.time["start"]["raw"].startswith("+0978") and r.time["end"]["raw"].startswith("+1016")


def test_war_participation_is_not_expanded_to_battles():
    person = entity("Q1", [claim("Q1$c", "P607", "QWAR")])
    rels = merge(extract(person))
    assert {(r.from_, r.to) for r in rels.values()} == {("Q1", "QWAR")}


# ---------------------------------------------------------------- overlap (three states)


def _rel(frm, to, kind, typ, start=None, end=None):
    r = Relationship(f"{frm}>{typ}>{to}", kind, typ, frm, to)
    if start:
        r.time["start"] = {"earliestJd": cal_jd(start), "latestJd": cal_jd(start) + 365, "raw": start, "precision": "year"}
    if end:
        r.time["end"] = {"earliestJd": cal_jd(end), "latestJd": cal_jd(end) + 365, "raw": end, "precision": "year"}
    return r


def test_activity_overlap_three_states():
    inside = _rel("P", "OFF", "office", "heldOffice", "1042-01-01", "1066-01-01")
    outside = _rel("P", "OFF", "office", "heldOffice", "0800-01-01", "0850-01-01")
    undated = _rel("P", "D", "dynasty", "memberOfDynasty")
    assert activity_overlap("P", [inside], {})[0] == "overlapping"
    assert activity_overlap("P", [outside], {})[0] == "not-overlapping"
    assert activity_overlap("P", [undated], {})[0] == "unknown"


# ---------------------------------------------------------------- tiers


def test_tiers():
    r = Relationship("a>parent>b", "kinship", "fatherOf", "a", "b")
    assert tier_of({"logic": "ok", "agreement": "both", "reference": "weak", "corroboration": "yes"}, r) == "verified"
    assert tier_of({"logic": "ok", "agreement": "one-sided", "reference": "weak", "corroboration": "yes"}, r) == "supported"
    assert tier_of({"logic": "ok", "agreement": "one-sided", "reference": "none", "corroboration": "no"}, r) == "review"
    assert tier_of({"logic": "fail", "agreement": "both", "reference": "strong", "corroboration": "yes"}, r) == "conflict"


def test_logic_flags_impossible_parent():
    parent = entity("A", [claim("A$b", "P569", time="+1050-00-00T00:00:00Z")])
    child = entity("B", [claim("B$b", "P569", time="+1040-00-00T00:00:00Z")])
    from crosscheck import lifetimes
    life = lifetimes({"A": parent, "B": child}, {"A", "B"})
    r = Relationship("A>parent>B", "kinship", "fatherOf", "A", "B")
    assess(r, life, {"A": parent, "B": child}, {})
    assert r.tier == "conflict" and "12 years" in r.checks["logicNote"]


# ---------------------------------------------------------------- shared identities


def test_story_views_merge_without_duplicates():
    import json
    from common import DATA_OUT
    views = sorted((DATA_OUT / "views").glob("*.json"))
    if len(views) < 2:
        import pytest
        pytest.skip("run build.py first")
    ents = {e["id"] for e in json.loads((DATA_OUT / "entities.json").read_text(encoding="utf-8"))}
    refs = [json.loads(v.read_text(encoding="utf-8"))["refs"] for v in views]
    merged = [r for rs in refs for r in rs]
    assert set(merged) <= ents, "every view ref must resolve to one shared entity"
    ids = [e["id"] for e in json.loads((DATA_OUT / "entities.json").read_text(encoding="utf-8"))]
    assert len(ids) == len(set(ids)), "shared dataset must not duplicate identities"
