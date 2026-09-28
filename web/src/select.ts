// Pure selectors (spec v1.0-draft §8, §10.4): same data + same state → same result, whatever the navigation history.
import type { Dataset, EventRec, Membership, RelRec } from "./data";

export const jdToYear = (jd: number): number => 2000 + (jd - 2451545.0) / 365.25;

/** Representative start/end on the timeline axis (midpoints of the date bounds — a display convention). */
export function eventSpan(ev: EventRec): [number, number] {
  const mid = (d: { earliestJd: number; latestJd: number }) => jdToYear((d.earliestJd + d.latestJd) / 2);
  const start = mid(ev.timing.start);
  const end = ev.timing.end ? mid(ev.timing.end) : ev.timing.temporalKind === "openSpan" ? start + 5 : start;
  return [start, Math.max(start, end)];
}

/** Reveal at the representative start, stay while the span lasts, then fade out over `fade` years. */
export function opacity(ev: EventRec, t: number, fade = 15): number {
  const [s, e] = eventSpan(ev);
  if (t < s) return 0;
  if (t <= e) return 1;
  return Math.max(0, 1 - (t - e) / fade);
}

export interface MarkerState {
  ev: EventRec;
  opacity: number;
  emphasis: "selected" | "story" | "other";
}

/** Markers to draw at time t. Selected record's events always show; story members are emphasised. */
export function visibleMarkers(
  events: EventRec[], t: number, selected: string | null, storyMembers: Set<string>,
): MarkerState[] {
  const out: MarkerState[] = [];
  for (const ev of events) {
    if (!ev.forms.includes("marker") || ev.location.assessment !== "located") continue;
    const isSel = selected !== null && (ev.entity === selected || ev.id === selected);
    const inStory = storyMembers.has(ev.entity);
    let o = opacity(ev, t, inStory ? 30 : 15);
    if (isSel) o = Math.max(o, 0.9);
    if (o <= 0) continue;
    out.push({ ev, opacity: inStory || isSel ? o : o * 0.45, emphasis: isSel ? "selected" : inStory ? "story" : "other" });
  }
  return out.sort((a, b) => (a.ev.year - b.ev.year) || a.ev.id.localeCompare(b.ev.id));
}

// ---------------------------------------------------------------- relationships, from one record's point of view

export const KIND_ORDER = [
  "kinship", "marriage", "dynasty", "office", "participation", "founding", "affiliation", "authorship",
  "structure", "claim", "interpretation",
] as const;

export const KIND_LABEL: Record<string, string> = {
  kinship: "Family", marriage: "Marriage", dynasty: "House", office: "Offices", participation: "Took part",
  founding: "Founding", affiliation: "Affiliation", authorship: "Works", structure: "Part of / sequence",
  claim: "Historical claims", interpretation: "Interpretations",
};

/** How the OTHER end of a relationship reads from `viewer`'s side. */
export function roleFromViewer(r: RelRec, viewer: string): string {
  const forward = r.from === viewer;
  const pair: Record<string, [string, string]> = {
    fatherOf: ["Child", "Father"], motherOf: ["Child", "Mother"], parentOf: ["Child", "Parent"],
    godparentOf: ["Godchild", "Godparent"], siblingOf: ["Sibling", "Sibling"], spouseOf: ["Spouse", "Spouse"],
    memberOfDynasty: ["House", "Member"], heldOffice: ["Office", "Held by"],
    participatedIn: ["Took part in", "Participant"], founded: ["Founded", "Founder"],
    commissioned: ["Commissioned", "Commissioned by"], architectOf: ["Designed", "Architect"],
    authorOf: ["Wrote", "Author"], creatorOf: ["Created", "Creator"], discovererOf: ["Discovered", "Discoverer"],
    notableWork: ["Notable work (unverified)", "Attributed to (unverified)"],
    memberOf: ["Member of", "Member"], religiousOrder: ["Order", "Member"], partOf: ["Part of", "Includes"],
    precedes: ["Followed by", "Preceded by"], sanctioned: ["Sanctioned", "Sanctioned by"],
  };
  const p = pair[r.type];
  return p ? (forward ? p[0] : p[1]) : r.type;
}

export function relKind(r: RelRec): string {
  if (r.layer === "claim") return "claim";
  if (r.layer === "interpretation") return "interpretation";
  return r.kind;
}

export interface RelGroup {
  kind: string;
  label: string;
  items: { rel: RelRec; other: string; role: string }[];
}

/** Relationships of one record, grouped by kind; verified before supported before unverified. */
export function groupRelations(ds: Dataset, viewer: string): RelGroup[] {
  const tierRank: Record<string, number> = { curated: 0, verified: 1, supported: 2, review: 3, conflict: 4 };
  const groups = new Map<string, RelGroup>();
  for (const r of ds.relsByEntity.get(viewer) ?? []) {
    const kind = relKind(r);
    const g = groups.get(kind) ?? { kind, label: KIND_LABEL[kind] ?? kind, items: [] };
    const other = r.from === viewer ? r.to : r.from;
    g.items.push({ rel: r, other, role: roleFromViewer(r, viewer) });
    groups.set(kind, g);
  }
  for (const g of groups.values()) {
    g.items.sort((a, b) => (tierRank[a.rel.tier] - tierRank[b.rel.tier]) ||
      (ds.entities.get(a.other)?.label ?? a.other).localeCompare(ds.entities.get(b.other)?.label ?? b.other));
  }
  return [...groups.values()].sort((a, b) =>
    KIND_ORDER.indexOf(a.kind as (typeof KIND_ORDER)[number]) - KIND_ORDER.indexOf(b.kind as (typeof KIND_ORDER)[number]));
}

// ---------------------------------------------------------------- stories

export function storyMembers(ds: Dataset, storyId: string): Set<string> {
  return new Set(ds.membersByStory.get(storyId)?.keys() ?? []);
}

/** Other stories this record belongs to — the visible "crossing" between stories through a shared record. */
export function otherStories(ds: Dataset, ref: string, current: string): Membership[] {
  const out: Membership[] = [];
  for (const [sid, members] of ds.membersByStory) {
    if (sid === current) continue;
    const m = members.get(ref);
    if (m) out.push(m);
  }
  return out;
}

/** Located event↔event links for arcs (entity relationships are never drawn on the map, §8). */
export function eventArcs(ds: Dataset, selected: string | null): { from: EventRec; to: EventRec; rel: RelRec }[] {
  if (!selected) return [];
  const markerOf = (entity: string) =>
    (ds.eventsByEntity.get(entity) ?? []).find((e) => e.location.assessment === "located" && e.forms.includes("marker"));
  const out: { from: EventRec; to: EventRec; rel: RelRec }[] = [];
  for (const r of ds.relsByEntity.get(selected) ?? []) {
    if (!["partOf", "precedes"].includes(r.type) || r.status === "rejected") continue;
    const a = markerOf(r.from), b = markerOf(r.to);
    if (a && b) out.push({ from: a, to: b, rel: r });
  }
  return out;
}
