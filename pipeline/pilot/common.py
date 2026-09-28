"""Shared helpers for the pilot pipeline (PROTOTYPE — connection-led branch, spec v1.0-draft).

Reuses the audit harness modules (wbapi, wdqs, rules) instead of duplicating them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "pipeline" / "audit"
if str(AUDIT) not in sys.path:
    sys.path.insert(0, str(AUDIT))

import rules as R  # noqa: E402  (pipeline/audit/rules.py)

CURATED = ROOT / "pipeline" / "curated"
REGISTRY = ROOT / "pipeline" / "registry" / "occurrences.json"
DATA_OUT = ROOT / "web" / "public" / "data" / "pilot"
REPORTS = ROOT / "docs" / "pilots"
SCOPE = yaml.safe_load((ROOT / "pipeline" / "config" / "scope.yaml").read_text(encoding="utf-8"))
STAGE = SCOPE["stages"][SCOPE["active_stage"]]

YEAR_DAYS = 365.25


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False), encoding="utf-8")


def cal_jd(date: str, calendar: str = "julian") -> float:
    y, m, d = (int(p) for p in date.split("-"))
    return R.jd_cal(y, m, d, R.JULIAN if calendar == "julian" else R.GREGORIAN)


WINDOW = (cal_jd(STAGE["from"], STAGE["calendar"]), cal_jd(STAGE["to_exclusive"], STAGE["calendar"]))


def overlaps(lo: float, hi: float, window: tuple[float, float] = WINDOW) -> bool:
    return lo < window[1] and window[0] < hi


# ---------------------------------------------------------------- entity JSON helpers


def qid_of(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def label(ent: dict | None, fallback: str = "") -> tuple[str, str]:
    """(label, language) — English first, then multilingual, then any (spec F14)."""
    if not ent:
        return fallback, ""
    labels = ent.get("labels", {})
    for lang in ("en", "mul"):
        if lang in labels:
            return labels[lang]["value"], lang
    for lang, v in sorted(labels.items()):
        return v["value"], lang
    return fallback or ent.get("id", ""), ""


def snak_item(snak: dict) -> str | None:
    if snak.get("snaktype") != "value":
        return None
    dv = snak.get("datavalue", {})
    return dv.get("value", {}).get("id") if dv.get("type") == "wikibase-entityid" else None


def snak_time(snak: dict) -> dict | None:
    if snak.get("snaktype") != "value" or snak.get("datavalue", {}).get("type") != "time":
        return None
    v = snak["datavalue"]["value"]
    return {"time": v["time"], "precision": v["precision"], "calendar": qid_of(v["calendarmodel"])}


def hist_date(tv: dict | None, statement: str = "") -> dict | None:
    """Entity-JSON time value → HistDate (source calendar → JD, §4.2). None if unusable."""
    if not tv:
        return None
    c = R.Claim(statement, "", tv["time"], tv["precision"], tv["calendar"], "NormalRank", wdqs_converted=False)
    R.compute_bounds(c)
    if not c.usable():
        return None
    return {"raw": tv["time"], "precision": R.PRECISION_NAMES.get(tv["precision"], str(tv["precision"])),
            "calendar": "julian" if tv["calendar"] == R.JULIAN else "gregorian",
            "earliestJd": c.earliest_jd, "latestJd": c.latest_jd, "statementId": statement}


def claims_date(ent: dict, prop: str) -> dict | None:
    """Resolve a date property with the v0.4 claim rules (preferred rank, overlap → one value, else envelope)."""
    claims = []
    for s in ent.get("claims", {}).get(prop, []):
        if s.get("rank") == "deprecated":
            continue
        tv = snak_time(s["mainsnak"])
        if not tv:
            continue
        c = R.Claim(s["id"], prop, tv["time"], tv["precision"], tv["calendar"],
                    "PreferredRank" if s.get("rank") == "preferred" else "NormalRank",
                    refs=len(s.get("references", [])), wdqs_converted=False)
        R.compute_bounds(c)
        claims.append(c)
    res = R.resolve_claims(claims)
    if res.status == "unusable":
        return None
    src = res.chosen or claims[0]
    return {"raw": src.raw, "precision": R.PRECISION_NAMES.get(src.precision, str(src.precision)),
            "calendar": "julian" if src.calendar == R.JULIAN else "gregorian",
            "earliestJd": res.earliest_jd, "latestJd": res.latest_jd, "statementId": src.statement,
            "status": res.status, "alternatives": res.alternatives}


def year_of(jd: float) -> float:
    return R.epoch_t(jd)


def coord(ent: dict | None) -> tuple[float, float] | None:
    """(lat, lon) from P625 on Earth, first statement by preferred rank."""
    if not ent:
        return None
    best = None
    for s in ent.get("claims", {}).get("P625", []):
        sn = s["mainsnak"]
        if sn.get("snaktype") != "value":
            continue
        v = sn["datavalue"]["value"]
        if qid_of(v.get("globe", "Q2")) != "Q2":
            continue
        if best is None or s.get("rank") == "preferred":
            best = (v["latitude"], v["longitude"])
    return best
