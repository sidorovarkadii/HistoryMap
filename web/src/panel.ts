// Side panel: record pages, relationship view, evidence, story path (spec v1.0-draft §3.3, §5.4, §8).
// Rendered as HTML strings; navigation uses data-* attributes handled by one delegated listener in main.ts.
import type { Dataset, EventRec, RelRec, Statement, StoryRec } from "./data";
import { groupRelations, jdToYear, otherStories } from "./select";

export const esc = (s: string): string =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

const TIER_BADGE: Record<string, [string, string]> = {
  verified: ["✓✓ verified", "Both sides of Wikidata or a strong reference, and corroborated by Wikipedia's link graph"],
  supported: ["✓ single-source", "One independent support (agreement, strong reference or corroboration)"],
  review: ["? unverified", "No agreement, strong reference or corroboration yet — shown, not relied on"],
  conflict: ["! conflict", "A logical check failed or sources disagree"],
  curated: ["✎ curated", "Added by hand with its own sources"],
};

export function badge(tier: string): string {
  const [text, title] = TIER_BADGE[tier] ?? [tier, ""];
  return `<span class="tier tier-${esc(tier)}" title="${esc(title)}">${esc(text)}</span>`;
}

const name = (ds: Dataset, id: string): string => ds.entities.get(id)?.label ?? id;
const link = (ds: Dataset, id: string): string =>
  ds.entities.has(id) ? `<a href="#" data-open="${esc(id)}">${esc(name(ds, id))}</a>` : esc(id);

export function fmtDate(d?: { raw: string; precision: string; earliestJd: number; latestJd: number; calendar?: string }): string {
  if (!d) return "";
  const y = Math.floor(jdToYear(d.earliestJd) + 0.001);
  if (["day", "month", "year"].includes(d.precision)) {
    const m = /^([+-])0*(\d+)-(\d\d)-(\d\d)/.exec(d.raw);
    if (!m) return String(y);
    const months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    if (d.precision === "day") return `${+m[4]} ${months[+m[3]]} ${m[2]}`;
    if (d.precision === "month") return `${months[+m[3]]} ${m[2]}`;
    return m[2];
  }
  if (d.precision === "decade") return `${y}s`;
  if (d.precision === "century") {
    const c = Math.floor((jdToYear(d.latestJd) - 1) / 100) + 1;
    return `${c}th century`;
  }
  return `c. ${y}`;
}

function eventDate(ev: EventRec): string {
  const s = fmtDate(ev.timing.start), e = fmtDate(ev.timing.end);
  const cal = ev.timing.start.calendar === "julian" && ev.timing.start.precision === "day" ? " (Julian)" : "";
  return (e && e !== s ? `${s} – ${e}` : ev.timing.temporalKind === "openSpan" ? `${s} – ?` : s) + cal;
}

function statementLine(ds: Dataset, s: Statement): string {
  const refs = s.references ?? [];
  const refText = refs.length === 0 ? `<span class="missing">no reference on this statement</span>` :
    refs.map((r) => r.strength === "strong"
      ? (r.statedIn ? `stated in ${link(ds, r.statedIn)}` : "") + (r.url ? ` <a href="${esc(r.url)}" target="_blank" rel="noopener">source URL</a>` : "")
      : r.strength === "weak" ? "imported from a Wikimedia project (weak)" : "reference without source").join("; ");
  const url = `https://www.wikidata.org/wiki/${encodeURIComponent(s.entity)}#${encodeURIComponent(s.property)}`;
  return `<li><a href="${url}" target="_blank" rel="noopener">${esc(name(ds, s.entity))} · ${esc(s.property)}</a>` +
    ` <span class="muted">statement ${esc(s.statementId.slice(-8))}${s.revision ? ` · rev ${s.revision}` : ""}</span> — ${refText}</li>`;
}

function evidenceBlock(ds: Dataset, r: RelRec): string {
  const rows: string[] = [];
  if (r.provenance === "curated") {
    rows.push(`<p>Curated connection. Sources: ${(r.sources ?? []).map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u.replace(/^https?:\/\//, ""))}</a>`).join(", ") || '<span class="missing">none</span>'}</p>`);
  } else {
    rows.push(`<ul class="stmts">${(r.statements ?? []).map((s) => statementLine(ds, s)).join("")}</ul>`);
    const c = r.checks ?? {};
    rows.push(`<p class="checks">Logic: ${esc(String(c.logic ?? "–"))}${c.logicNote ? ` (${esc(String(c.logicNote))})` : ""} · ` +
      `both sides: ${esc(String(c.agreement ?? "–"))} · reference: ${esc(String(c.reference ?? "–"))} · ` +
      `Wikipedia link: ${esc(String(c.corroboration ?? "–"))}</p>`);
  }
  if (r.uncertainty) rows.push(`<p class="uncertain">⚠ ${esc(r.uncertainty)}</p>`);
  if (r.tier === "review") rows.push(`<p class="missing">Evidence missing: nothing independent supports this link yet — it is shown, not relied on.</p>`);
  return rows.join("");
}

function relItem(ds: Dataset, item: { rel: RelRec; other: string; role: string }, story: string): string {
  const r = item.rel;
  const cross = otherStories(ds, item.other, story);
  const crossChip = cross.length && !(ds.membersByStory.get(story)?.has(item.other))
    ? `<button class="cross" data-story="${esc(cross[0].story)}" data-open="${esc(item.other)}" title="This record belongs to another story">↗ ${esc(storyTitle(ds, cross[0].story))}</button>` : "";
  const time = [fmtDate(r.time?.start), fmtDate(r.time?.end)].filter(Boolean).join(" – ");
  return `<li class="rel kind-${esc(r.layer === "relationship" || !r.layer ? r.kind : r.layer)}">
    <div class="rel-head"><span class="role">${esc(item.role)}</span> ${link(ds, item.other)} ${time ? `<span class="muted">${esc(time)}</span>` : ""} ${badge(r.tier)} ${crossChip}</div>
    <details><summary>${esc(r.explanation ?? "")}</summary>${evidenceBlock(ds, r)}</details>
  </li>`;
}

const storyTitle = (ds: Dataset, id: string): string => ds.stories.find((s) => s.id === id)?.title ?? id;

export function renderRecord(ds: Dataset, id: string, story: string): string {
  const e = ds.entities.get(id);
  if (!e) return `<p class="missing">Record ${esc(id)} is not in the pilot dataset.</p>`;
  const membership = ds.membersByStory.get(story)?.get(id);
  const others = otherStories(ds, id, story);
  const evs = (ds.eventsByEntity.get(id) ?? []).slice().sort((a, b) => a.year - b.year);
  const located = evs.some((x) => x.location.assessment === "located");
  const parts: string[] = [];
  parts.push(`<div class="rec-head"><div class="kind">${esc(e.kind)}${e.classes.length ? ` · ${esc(e.classes.slice(0, 2).join(", "))}` : ""}</div>
    <h2>${esc(e.label)}${e.labelLang && e.labelLang !== "en" ? ` <span class="muted">[${esc(e.labelLang)}]</span>` : ""}</h2>
    ${e.lifespan ? `<div class="muted">${esc(e.lifespan.birth ?? "?")} – ${esc(e.lifespan.death ?? "?")}</div>` : ""}
    ${e.description ? `<p class="desc">${esc(e.description)}</p>` : ""}
    <div class="links"><a href="${esc(e.wikidata)}" target="_blank" rel="noopener">Wikidata</a>${e.wikipedia ? ` · <a href="${esc(e.wikipedia)}" target="_blank" rel="noopener">Wikipedia</a>` : ""}</div></div>`);
  if (membership) {
    parts.push(`<div class="membership role-${esc(membership.role)}"><b>${esc(membership.role)}</b> in this story — ${esc(membership.explanation)}</div>`);
  }
  if (others.length) {
    parts.push(`<div class="also">Also in: ${others.map((m) => `<button class="cross" data-story="${esc(m.story)}" data-open="${esc(id)}">↗ ${esc(storyTitle(ds, m.story))} (${esc(m.role)})</button>`).join(" ")}</div>`);
  }
  if (!located) parts.push(`<div class="unlocated">No map location — explore through its connections and the timeline.</div>`);
  if (evs.length) {
    parts.push(`<h3>On the timeline</h3><ul class="evs">${evs.map((x) => `<li><button data-jump="${esc(x.id)}">${esc(eventDate(x))}</button> ${esc(x.title)}${x.location.assessment === "located" ? "" : ' <span class="muted">(unlocated)</span>'}</li>`).join("")}</ul>`);
  }
  const groups = groupRelations(ds, id);
  if (!groups.length) parts.push(`<p class="missing">No evidenced connections in the pilot dataset.</p>`);
  for (const g of groups) {
    parts.push(`<h3 class="grp kind-${esc(g.kind)}">${esc(g.label)} <span class="muted">${g.items.length}</span></h3>
      <ul class="rels">${g.items.map((it) => relItem(ds, it, story)).join("")}</ul>`);
  }
  return parts.join("");
}

export function renderStory(ds: Dataset, s: StoryRec, step: number): string {
  const path = s.path.map((p, i) => {
    const links = (ds.relsByEntity.get(p.ref) ?? []).filter((r) => r.status === "published").length;
    return `<li class="${i === step ? "current" : ""}"><button data-step="${i}">${i + 1}. ${esc(name(ds, p.ref))}</button>
      <span class="muted">${esc(p.note)}</span>${links === 0 ? ' <span class="missing">no evidenced link yet</span>' : ""}</li>`;
  }).join("");
  const exits = s.exits.map((x) => {
    const cross = otherStories(ds, x.ref, s.id);
    return `<li><a href="#" data-open="${esc(x.ref)}">${esc(name(ds, x.ref))}</a> — <span class="muted">${esc(x.note)}</span>
      ${cross.length ? `<button class="cross" data-story="${esc(cross[0].story)}" data-open="${esc(x.ref)}">↗ ${esc(storyTitle(ds, cross[0].story))}</button>` : ""}</li>`;
  }).join("");
  const roles = { anchor: 0, connecting: 0, context: 0 } as Record<string, number>;
  for (const m of s.memberships) roles[m.role] = (roles[m.role] ?? 0) + 1;
  return `<div class="story-head"><div class="kind">story</div><h2>${esc(s.title)}</h2><p class="desc">${esc(s.question)}</p>
    <p class="muted">${roles.anchor} anchors · ${roles.connecting} connecting · ${roles.context} context — the reading path below is an editorial order, not a historical relationship.</p></div>
    <h3>Reading path</h3><ol class="path">${path}</ol>
    <div class="step-nav"><button data-step="${Math.max(0, step - 1)}">← previous</button><button data-step="${Math.min(s.path.length - 1, step + 1)}">next in this story →</button></div>
    <h3>Continue exploring</h3><ul class="exits">${exits}</ul>`;
}
