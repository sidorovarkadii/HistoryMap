// Shared pilot dataset (spec v1.0-draft §2): one identity per record; stories are entry points, not partitions.

export interface HistDate {
  raw: string;
  precision: string;
  calendar: "julian" | "gregorian";
  earliestJd: number;
  latestJd: number;
}

export interface Location {
  assessment: "located" | "unknown" | "distributed" | "not-applicable";
  lat?: number;
  lon?: number;
  precision?: string;
  evidence?: string;
}

export interface EntityRec {
  id: string;
  kind: string;
  label: string;
  labelLang: string;
  description: string;
  classes: string[];
  wikidata: string;
  wikipedia?: string;
  lifespan?: { birth?: string; death?: string };
  stories: { story: string; role: string }[];
}

export interface EventRec {
  id: string;
  entity: string;
  eventType: string;
  title: string;
  year: number;
  timing: { temporalKind: "point" | "span" | "openSpan"; start: HistDate; end?: HistDate };
  location: Location;
  forms: string[];
}

export interface Reference {
  strength: "strong" | "weak" | "none";
  statedIn?: string;
  url?: string;
  importedFrom?: string;
  retrieved?: string;
}

export interface Statement {
  entity: string;
  property: string;
  statementId: string;
  revision?: number;
  references: Reference[];
}

export interface RelRec {
  id: string;
  kind: string;
  type: string;
  from: string;
  to: string;
  layer?: "relationship" | "claim" | "interpretation";
  provenance?: "imported" | "derived" | "curated";
  statements?: Statement[];
  sources?: string[];
  time?: { start?: HistDate; end?: HistDate };
  qualifiers?: Record<string, string>;
  conflicts?: string[];
  explanation?: string;
  uncertainty?: string;
  tier: "verified" | "supported" | "review" | "conflict" | "curated";
  checks?: Record<string, unknown>;
  status: "published" | "candidate" | "rejected";
}

export interface Membership {
  story: string;
  ref: string;
  role: "anchor" | "connecting" | "context";
  explanation: string;
  sources?: string[];
}

export interface StoryRec {
  id: string;
  title: string;
  question: string;
  window: { from: string; to_exclusive: string };
  memberships: Membership[];
  path: { ref: string; note: string }[];
  exits: { ref: string; note: string }[];
}

export interface Dataset {
  entities: Map<string, EntityRec>;
  events: EventRec[];
  rels: RelRec[];
  stories: StoryRec[];
  eventsByEntity: Map<string, EventRec[]>;
  relsByEntity: Map<string, RelRec[]>;
  membersByStory: Map<string, Map<string, Membership>>;
}

export function buildIndexes(entities: EntityRec[], events: EventRec[], rels: RelRec[], stories: StoryRec[]): Dataset {
  const eventsByEntity = new Map<string, EventRec[]>();
  for (const e of events) {
    const list = eventsByEntity.get(e.entity) ?? [];
    list.push(e);
    eventsByEntity.set(e.entity, list);
  }
  const relsByEntity = new Map<string, RelRec[]>();
  for (const r of rels) {
    if (r.status === "rejected") continue;
    for (const end of [r.from, r.to]) {
      const list = relsByEntity.get(end) ?? [];
      list.push(r);
      relsByEntity.set(end, list);
    }
  }
  const membersByStory = new Map<string, Map<string, Membership>>();
  for (const s of stories) membersByStory.set(s.id, new Map(s.memberships.map((m) => [m.ref, m])));
  return {
    entities: new Map(entities.map((e) => [e.id, e])),
    events, rels, stories, eventsByEntity, relsByEntity, membersByStory,
  };
}

export async function loadDataset(base = "/data/pilot"): Promise<Dataset> {
  const get = async <T>(name: string): Promise<T> => {
    const res = await fetch(`${base}/${name}.json`);
    if (!res.ok) throw new Error(`failed to load ${name}.json (${res.status})`);
    return res.json() as Promise<T>;
  };
  const [entities, events, rels, stories] = await Promise.all([
    get<EntityRec[]>("entities"), get<EventRec[]>("events"), get<RelRec[]>("relationships"), get<StoryRec[]>("stories"),
  ]);
  return buildIndexes(entities, events, rels, stories);
}
