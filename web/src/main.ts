// Walkthrough entry: state + wiring. State = (t, story, selection, path step); rendering is a pure function of it.
import "./style.css";
import { loadDataset, type Dataset, type EventRec } from "./data";
import { MapView } from "./map";
import { esc, renderRecord, renderStory } from "./panel";
import { eventArcs, eventSpan, jdToYear, storyMembers, visibleMarkers } from "./select";

interface State { t: number; story: string; selected: string | null; step: number; playing: boolean; speed: number }

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

async function start(): Promise<void> {
  const ds = await loadDataset();
  const state: State = { t: 1042, story: ds.stories[0].id, selected: null, step: 0, playing: false, speed: 5 };
  const scrub = $<HTMLInputElement>("scrub"), yearEl = $("year"), panel = $("panel");
  const view = new MapView($("map"), (ev) => select(ev.entity, false));

  const story = () => ds.stories.find((s) => s.id === state.story)!;
  const windowYears = (): [number, number] => {
    const w = story().window;
    const y = (d: string) => parseInt(d.slice(0, 4), 10);
    return [y(w.from), y(w.to_exclusive)];
  };

  // ---------------------------------------------------------------- render (pure function of state)
  function renderMap(): void {
    view.update(visibleMarkers(ds.events, state.t, state.selected, storyMembers(ds, state.story)),
      eventArcs(ds, state.selected));
  }
  function renderPanel(): void {
    if (!state.selected) {
      panel.innerHTML = renderStory(ds, story(), state.step);
    } else {
      const s = story();
      const i = s.path.findIndex((p) => p.ref === state.selected);
      const stepNav = i < 0 ? "" : `<div class="step-bar"><span class="muted">Step ${i + 1}/${s.path.length} — ${esc(s.path[i].note)}</span>
        <div class="step-nav">${i > 0 ? `<button data-step="${i - 1}">← previous</button>` : "<span></span>"}
        ${i < s.path.length - 1 ? `<button data-step="${i + 1}">next in this story →</button>` : ""}</div></div>`;
      panel.innerHTML = `<button class="back" data-back>← ${esc(s.title)}</button>${stepNav}` +
        renderRecord(ds, state.selected, state.story);
    }
    panel.scrollTop = 0;
  }
  function renderTimeline(): void {
    scrub.value = String(state.t);
    yearEl.textContent = String(Math.floor(state.t));
  }
  function renderTabs(): void {
    $("story-tabs").innerHTML = ds.stories.map((s) =>
      `<button data-story="${esc(s.id)}" class="${s.id === state.story ? "active" : ""}">${esc(s.title)}</button>`).join("");
  }
  function renderTicks(): void {
    const [lo, hi] = windowYears();
    const members = storyMembers(ds, state.story);
    $("ticks").innerHTML = ds.events.filter((e) => members.has(e.entity) && e.year >= lo && e.year < hi)
      .map((e) => `<span class="tick ${e.forms.includes("marker") ? "" : "unlocated"}" style="left:${((e.year - lo) / (hi - lo)) * 100}%" title="${esc(e.title)}"></span>`).join("");
  }
  function renderAll(): void { renderMap(); renderPanel(); renderTimeline(); }

  // ---------------------------------------------------------------- actions
  function setStory(id: string): void {
    state.story = id;
    state.step = 0;
    const [lo, hi] = windowYears();
    scrub.min = String(lo);
    scrub.max = String(hi);
    state.t = Math.min(Math.max(state.t, lo), hi);
    renderTabs();
    renderTicks();
  }
  function jumpTo(ev: EventRec): void {
    state.t = eventSpan(ev)[0] + 0.01;
    view.flyTo(ev);
  }
  function select(id: string | null, jump = true): void {
    state.selected = id;
    if (id && jump) {
      const ev = (ds.eventsByEntity.get(id) ?? []).find((e) => e.forms.includes("marker")) ?? ds.eventsByEntity.get(id)?.[0];
      if (ev) jumpTo(ev);
    }
    renderAll();
  }

  // ---------------------------------------------------------------- events
  document.addEventListener("click", (e) => {
    const el = (e.target as HTMLElement).closest<HTMLElement>("[data-open],[data-jump],[data-step],[data-story],[data-back]");
    if (!el) return;
    e.preventDefault();
    if (el.dataset.story) setStory(el.dataset.story);
    if (el.dataset.back !== undefined) return select(null);
    if (el.dataset.step !== undefined) {
      state.step = +el.dataset.step;
      const ref = story().path[state.step]?.ref;
      return select(ref ?? null); // open the step's record; select() also moves the timeline and map
    }
    if (el.dataset.jump) {
      const ev = ds.events.find((x) => x.id === el.dataset.jump);
      if (ev) jumpTo(ev);
      return renderAll();
    }
    if (el.dataset.open) return select(el.dataset.open);
    renderAll();
  });

  scrub.addEventListener("input", () => { state.t = +scrub.value; renderMap(); yearEl.textContent = String(Math.floor(state.t)); });
  $<HTMLSelectElement>("speed").addEventListener("change", (e) => { state.speed = +(e.target as HTMLSelectElement).value; });

  let last = 0;
  const tick = (now: number) => {
    if (!state.playing) return;
    const dt = last ? (now - last) / 1000 : 0;
    last = now;
    const hi = windowYears()[1];
    state.t += dt * state.speed;
    if (state.t >= hi) { state.t = hi; state.playing = false; $("play").textContent = "▶"; }
    renderMap();
    renderTimeline();
    if (state.playing) requestAnimationFrame(tick);
  };
  $("play").addEventListener("click", () => {
    state.playing = !state.playing;
    $("play").textContent = state.playing ? "❚❚" : "▶";
    if (state.playing) {
      const [lo, hi] = windowYears();
      if (state.t >= hi - 0.5) state.t = lo;
      last = 0;
      requestAnimationFrame(tick);
    } else renderAll();
  });

  // search across all records (entities and events), including unlocated ones
  const search = $<HTMLInputElement>("search"), results = $("search-results");
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    if (q.length < 2) { results.hidden = true; return; }
    const hits = [...ds.entities.values()].filter((x) => x.label.toLowerCase().includes(q)).slice(0, 12);
    results.innerHTML = hits.map((h) => `<button data-open="${esc(h.id)}">${esc(h.label)} <span class="muted">${esc(h.kind)}</span></button>`).join("")
      || `<div class="muted">No match</div>`;
    results.hidden = false;
  });
  document.addEventListener("click", (e) => {
    if (!(e.target as HTMLElement).closest("#search, #search-results")) results.hidden = true;
  });

  setStory(state.story);
  renderAll();
  (window as unknown as { __hm: unknown }).__hm = { ds, state, select, jdToYear }; // walkthrough inspection hook
}

start().catch((err) => {
  document.getElementById("panel")!.textContent = `Could not load the pilot dataset: ${String(err)}`;
});

export type { Dataset };
