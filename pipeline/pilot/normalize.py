"""Normalisation: selected claims → playable content (spec v1.0 §6, §8).

Produces canonical dated events, life events for admitted people, founding events for dated institutions,
office tenures as timeline spans (relationships, not events), and a presentation record for every item.
Entities without a dated event stay in the dataset (panel-only); nothing is manufactured to fill a timeline.
"""
from __future__ import annotations

import json

from common import REGISTRY, R, claims_date, coord, hist_date, label, snak_item, year_of
from expand import classify


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}


def save_registry(reg: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


SETTLEMENT_WORDS = ("city", "town", "village", "settlement", "commune", "municipality", "abbey", "monastery",
                    "castle", "cathedral", "church", "palace", "fortification", "hill", "field", "battlefield")


def locate_event(ent: dict, ents: dict, class_labels: dict) -> dict:
    """Location with evidence (§4.3): P625 on the item → P276 target's coordinates → unknown."""
    c = coord(ent)
    if c:
        return {"assessment": "located", "lat": c[0], "lon": c[1], "role": "eventSite", "precision": "exact",
                "evidence": f"P625 on {ent['id']}"}
    for s in ent.get("claims", {}).get("P276", []):
        place = snak_item(s["mainsnak"])
        pc = coord(ents.get(place))
        if pc:
            _, names = classify(ents[place], class_labels)
            low = " ".join(names).lower()
            precision = "settlement" if any(w in low for w in SETTLEMENT_WORDS) else "region"
            return {"assessment": "located", "lat": pc[0], "lon": pc[1], "role": "eventSite",
                    "precision": precision, "evidence": f"P276 → {place} P625 ({precision}, from its type)"}
    return {"assessment": "unknown"}


def locate_place_prop(ent: dict, prop: str, ents: dict) -> dict:
    for s in ent.get("claims", {}).get(prop, []):
        place = snak_item(s["mainsnak"])
        pc = coord(ents.get(place))
        if pc:
            return {"assessment": "located", "lat": pc[0], "lon": pc[1], "role": "settlement",
                    "precision": "settlement", "evidence": f"{prop} → {place} P625"}
    return {"assessment": "unknown"}


def timing(ent: dict) -> dict | None:
    start = claims_date(ent, "P580")
    end = claims_date(ent, "P582")
    if start:
        return {"temporalKind": "span" if end else "openSpan", "start": start, **({"end": end} if end else {})}
    point = claims_date(ent, "P585")
    if point:
        return {"temporalKind": "point", "start": point}
    if end:
        return {"temporalKind": "openSpan", "start": end, "note": "only an end date is recorded"}
    return None


def curated_date(date: str) -> dict:
    """'1077-01' / '1077' → HistDate in the Julian calendar (curated override)."""
    parts = date.split("-")
    y, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    return hist_date({"time": f"+{y:04d}-{m:02d}-00T00:00:00Z", "precision": 10 if m else 9, "calendar": R.JULIAN},
                     "curated")


def normalize(admitted: dict[str, dict], kinds: dict[str, str], ents: dict, class_labels: dict,
              rels: list, anchors: set[str], overrides: dict | None = None) -> tuple[list[dict], list[dict], dict]:
    """Returns (events, presentation, registry). `overrides` = curated seed corrections (kind/date/place)."""
    overrides = overrides or {}
    reg = load_registry()
    events, pres = [], []
    pending = []

    def add_event(entity, etype, title, tm, loc, stmts, forms):
        pending.append((entity, etype, stmts))
        events.append({"entity": entity, "eventType": etype, "title": title, "timing": tm, "location": loc,
                       "forms": forms})

    for q in sorted(admitted):
        ent, kind = ents.get(q), kinds.get(q, "other")
        if not ent:
            continue
        name = label(ent, q)[0]
        if kind == "event":
            ov = overrides.get(q, {})
            tm = timing(ent)
            if not tm and ov.get("date"):
                tm = {"temporalKind": "point", "start": curated_date(ov["date"]), "curated": ov.get("source", "")}
            loc = locate_event(ent, ents, class_labels)
            if loc["assessment"] != "located" and ov.get("placeQid"):
                pc = coord(ents.get(ov["placeQid"]))
                if pc:
                    loc = {"assessment": "located", "lat": pc[0], "lon": pc[1], "role": "eventSite",
                           "precision": "settlement",
                           "evidence": f"curated: {ov['place']} ({ov['placeQid']} P625); source {ov.get('source', '')}"}
            _, cls = classify(ent, class_labels)
            etype = (ov.get("eventType") or (cls[0] if cls else "event")).lower()
            if tm:
                forms = ["timeline"] + (["marker"] if loc["assessment"] == "located" and
                                        tm["start"]["precision"] in ("day", "month", "year") else [])
                add_event(q, etype, name, tm, loc, [tm["start"]["statementId"]], forms)
            pres.append({"ref": q, "forms": ["panel"] + (["timeline"] if tm else []),
                         "location": loc["assessment"]})
        elif kind == "work":
            # Creation date only; P577 on manuscripts is usually a modern edition (audit F6), so it is not used.
            d = claims_date(ent, "P571")
            if d:
                add_event(q, "created", f"Creation of {name}", {"temporalKind": "point", "start": d},
                          {"assessment": "unknown"}, [d["statementId"]], ["timeline"])
            pres.append({"ref": q, "forms": ["panel"] + (["timeline"] if d else []), "location": "unknown"})
        elif kind == "person":
            for prop, etype, place_prop in (("P569", "birth", "P19"), ("P570", "death", "P20")):
                d = claims_date(ent, prop)
                if not d:
                    continue
                loc = locate_place_prop(ent, place_prop, ents)
                forms = ["timeline"] + (["marker"] if q in anchors and loc["assessment"] == "located"
                                        and d["precision"] in ("day", "month", "year") else [])
                add_event(q, etype, f"{etype.capitalize()} of {name}", {"temporalKind": "point", "start": d},
                          loc, [d["statementId"]], forms)
            pres.append({"ref": q, "forms": ["panel"], "location": "not-applicable"})
        elif kind == "institution":
            d = claims_date(ent, "P571")
            c = coord(ent)
            loc = ({"assessment": "located", "lat": c[0], "lon": c[1], "role": "buildingSite", "precision": "exact",
                    "evidence": f"P625 on {q}"} if c else {"assessment": "unknown"})
            if d:
                forms = ["timeline"] + (["marker"] if c and d["precision"] in ("day", "month", "year") else [])
                add_event(q, "founded", f"Foundation of {name}", {"temporalKind": "point", "start": d},
                          loc, [d["statementId"]], forms)
            pres.append({"ref": q, "forms": ["panel"], "location": loc["assessment"]})
        else:
            pres.append({"ref": q, "forms": ["panel"],
                         "location": "not-applicable" if kind in ("office", "dynasty", "polity") else "unknown"})

    ids, _ = R.assign_ids(pending, reg)
    for ev, eid in zip(events, ids):
        ev["id"] = eid
        ev["year"] = round(year_of(R.rt(ev["timing"]["start"]["earliestJd"], ev["timing"]["start"]["latestJd"])), 3)
    # office tenures → timeline spans on the holder (relationships, not events)
    for r in rels:
        if r.type == "heldOffice" and r.time and r.status == "published":
            pres.append({"ref": r.id, "forms": ["span"], "location": "not-applicable"})
    return events, pres, reg
