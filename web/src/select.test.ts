import { describe, expect, it } from "vitest";
import { buildIndexes, type EventRec, type RelRec } from "./data";
import { eventArcs, eventSpan, groupRelations, opacity, otherStories, roleFromViewer, visibleMarkers } from "./select";

const JD1066 = 2110700; // ~1066 on the Julian-day axis
const ev = (id: string, entity: string, jd: number, located = true, forms = ["timeline", "marker"]): EventRec => ({
  id, entity, eventType: "battle", title: id, year: 2000 + (jd - 2451545) / 365.25,
  timing: { temporalKind: "point", start: { raw: "", precision: "day", calendar: "julian", earliestJd: jd, latestJd: jd + 1 } },
  location: located ? { assessment: "located", lat: 50, lon: 0 } : { assessment: "unknown" }, forms,
});
const rel = (id: string, from: string, type: string, to: string, kind: string, tier: RelRec["tier"] = "verified"): RelRec =>
  ({ id, from, to, type, kind, tier, status: "published" });

describe("reveal and fade", () => {
  const e = ev("E", "Q1", JD1066);
  const y = eventSpan(e)[0]; // representative time (midpoint of the date bounds), §4.2
  it("is hidden before, full at, and fades after the event", () => {
    expect(opacity(e, y - 1)).toBe(0);
    expect(opacity(e, y)).toBe(1);
    expect(opacity(e, y + 7.5, 15)).toBeCloseTo(0.5, 1);
    expect(opacity(e, y + 20, 15)).toBe(0);
  });
  it("is deterministic: same t gives same markers whatever came before", () => {
    const evs = [e, ev("F", "Q2", JD1066 + 400)];
    const a = visibleMarkers(evs, y + 1, null, new Set());
    visibleMarkers(evs, y + 50, null, new Set());
    expect(visibleMarkers(evs, y + 1, null, new Set())).toEqual(a);
  });
  it("never draws unlocated events as markers", () => {
    expect(visibleMarkers([ev("U", "Q3", JD1066, false)], 2000, null, new Set())).toHaveLength(0);
  });
});

describe("relationships from a viewer's side", () => {
  const r = rel("a>parent>b", "A", "fatherOf", "B", "kinship");
  it("reads the other end correctly", () => {
    expect(roleFromViewer(r, "A")).toBe("Child");
    expect(roleFromViewer(r, "B")).toBe("Father");
  });
  it("groups by kind and keeps claims separate from relationships", () => {
    const claim = { ...rel("c", "P", "sanctioned", "A", "claim", "curated"), layer: "claim" as const };
    const ds = buildIndexes([], [], [r, claim, rel("m", "A", "spouseOf", "C", "marriage")], []);
    const kinds = groupRelations(ds, "A").map((g) => g.kind);
    expect(kinds).toEqual(["kinship", "marriage", "claim"]);
  });
});

describe("stories share records", () => {
  it("reports the other story a shared record belongs to", () => {
    const stories = [
      { id: "s1", title: "", question: "", window: { from: "", to_exclusive: "" }, path: [], exits: [],
        memberships: [{ story: "s1", ref: "X", role: "anchor" as const, explanation: "" }] },
      { id: "s2", title: "", question: "", window: { from: "", to_exclusive: "" }, path: [], exits: [],
        memberships: [{ story: "s2", ref: "X", role: "context" as const, explanation: "" }] },
    ];
    const ds = buildIndexes([], [], [], stories);
    expect(otherStories(ds, "X", "s1").map((m) => m.story)).toEqual(["s2"]);
  });
  it("draws arcs only between located events", () => {
    const a = ev("A:battle", "A", JD1066), b = ev("B:battle", "B", JD1066 + 20), c = ev("C:x", "C", JD1066, false);
    const ds = buildIndexes([], [a, b, c], [rel("p", "A", "precedes", "B", "structure"), rel("q", "A", "precedes", "C", "structure")], []);
    expect(eventArcs(ds, "A").map((x) => x.to.id)).toEqual(["B:battle"]);
  });
});
