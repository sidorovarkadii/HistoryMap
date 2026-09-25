"""Milestone 1 audit — step 3: Stage 1 dataset projections (THROWAWAY audit harness).

Answers: how many map-ready events per category at each prominence threshold; how large the
"century pulse" is; how well life events connect to war events through participants.

    python pipeline/audit/stage1_projection.py   (after sample.py + measure.py)
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import measure as M  # noqa: E402

THRESHOLDS = [5, 10, 20, 40]
out = ["# Stage 1 projections (generated)", "",
       "> `pipeline/audit/stage1_projection.py`. *Map-ready* = retained, located in bbox, precision year or finer, "
       "status ok. Counts extrapolated to the full candidate set where the category was sampled.", ""]

cats = {}
for cat in M.CATEGORY_ORDER:
    data = M.load(cat)
    if not data:
        continue
    evs = M.events_for(cat, data)
    keep = [e for e in evs if M.retained(e)[0]]
    scale = data["candidates_total"] / max(1, data.get("sampled_total", data["detailed_total"]))
    cats[cat] = (data, keep, scale)

out += ["## Map-ready events by prominence threshold (sitelinks ≥ T)", "",
        "| category | all retained | map-ready | T≥5 | T≥10 | T≥20 | T≥40 |", "|---|---|---|---|---|---|---|"]
for cat, (data, keep, scale) in cats.items():
    ready = [e for e in keep if e.lat is not None and e.precision >= 9 and e.status == "ok"]
    row = [round(len(keep) * scale), round(len(ready) * scale)]
    row += [round(sum(1 for e in ready if e.sitelinks >= t) * scale) for t in THRESHOLDS]
    out.append(f"| {cat} | " + " | ".join(map(str, row)) + " |")
out.append("")

out += ["## Century pulse — events that would reveal at the same instant", "",
        "Events dated coarser than a year reveal at their interval midpoint (§4.3). Largest same-year clusters "
        "among retained, located events:", "", "| category | coarser than year (located) | top same-year clusters |", "|---|---|---|"]
for cat, (data, keep, scale) in cats.items():
    coarse = [e for e in keep if e.precision < 9 and e.lat is not None]
    clusters = Counter(int(e.year) for e in coarse).most_common(3)
    out.append(f"| {cat} | {round(len(coarse) * scale)} | "
               + ", ".join(f"{y}: {round(c * scale)}" for y, c in clusters) + " |")
out.append("")

# life ↔ war: war events whose participants (P710) are people in the life set → "events involving" links
if "war" in cats and "life" in cats:
    life_data, life_keep, life_scale = cats["life"]
    life_people = set(life_data["items"])
    war_keep = cats["war"][1]
    linked = [e for e in war_keep if any(t in life_people for t in e.rel_targets.get("P710", []))]
    people_hit = {t for e in war_keep for t in e.rel_targets.get("P710", []) if t in life_people}
    out += ["## Life ↔ war connectivity (via P710 participant — the `eventsInvolving` index)", "",
            f"- War events naming a sampled person as participant: {len(linked)} of {len(war_keep)} "
            f"(≈ {min(len(war_keep), round(len(linked) * life_scale))} if all {life_data['candidates_total']} people were fetched)",
            f"- Distinct sampled people involved: {len(people_hit)} (≈ {round(len(people_hit) * life_scale)} extrapolated)",
            "- Life events have almost no outgoing links (97% none); their connections come from **reverse** "
            "participant links and `sameSubject` (birth↔death), exactly the v0.4 §6 indexes.", ""]

path = M.DOCS / "stage1-projection.md"
path.write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
