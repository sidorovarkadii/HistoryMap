"""Entity store: every cached entity payload indexed by QID (spec v1.0 §9 step 2).

The audit cached wbgetentities responses per *batch*, so a new batch composition used to mean a re-download.
The store indexes all cached payloads by entity (keeping the highest `lastrevid`) and fetches only what is missing.
Also resolves English Wikipedia titles to QIDs and lists the QIDs an enwiki article links to (corroboration, §10).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

from common import ROOT

import wbapi  # pipeline/audit/wbapi.py
import wdqs   # pipeline/audit/wdqs.py

ENWIKI = "https://en.wikipedia.org/w/api.php"
MW_CACHE = ROOT / "pipeline" / "cache" / "mwapi"


class EntityStore:
    def __init__(self, cache_dir: Path = wbapi.CACHE_DIR):
        self.index: dict[str, dict] = {}
        self.fetched = 0
        for p in sorted(cache_dir.glob("*.json")):
            try:
                ents = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            for key, ent in ents.items():
                self._add(key, ent)

    def _add(self, key: str, ent: dict) -> None:
        if not ent or "missing" in ent:
            return
        for k in {key, ent.get("id", key)}:
            cur = self.index.get(k)
            if cur is None or ent.get("lastrevid", 0) >= cur.get("lastrevid", 0):
                self.index[k] = ent

    def get(self, qids) -> dict[str, dict]:
        """Return {qid: entity JSON}; fetch only those not already cached (batches of 50)."""
        want = sorted({q for q in qids if q and q[0] in "QP" and q[1:].isdigit()})
        missing = [q for q in want if q not in self.index]
        for i in range(0, len(missing), 50):
            chunk = missing[i:i + 50]
            ents = wbapi.get_entities(chunk)
            self.fetched += len(chunk)
            for k, e in ents.items():
                self._add(k, e)
        return {q: self.index[q] for q in want if q in self.index}

    def one(self, qid: str) -> dict | None:
        return self.get([qid]).get(qid)


# ---------------------------------------------------------------- MediaWiki (enwiki) helpers

mw_stats = {"hits": 0, "requests": 0}
_last = 0.0


def mw_get(params: dict, endpoint: str = ENWIKI) -> dict:
    """Cached GET against a MediaWiki API (validate-before-cache, 1 request/s, polite User-Agent)."""
    params = {**params, "format": "json", "formatversion": "2"}
    key = hashlib.sha256((endpoint + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    path = MW_CACHE / f"{key}.json"
    if path.exists():
        mw_stats["hits"] += 1
        return json.loads(path.read_text(encoding="utf-8"))
    global _last
    delay = 5.0
    for attempt in range(1, 7):
        wait = 1.0 - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
        mw_stats["requests"] += 1
        try:
            r = requests.get(endpoint, params=params, headers={"User-Agent": wdqs.USER_AGENT}, timeout=60)
            if r.status_code == 200:
                data = r.json()
                if "error" in data and data["error"].get("code") == "maxlag":
                    time.sleep(delay)
                    delay *= 2
                    continue
                MW_CACHE.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                return data
            if r.status_code in (429, 500, 502, 503, 504):
                ra = r.headers.get("Retry-After")
                time.sleep(float(ra) if ra and ra.isdigit() else delay)
                delay *= 2
                continue
            raise RuntimeError(f"MediaWiki HTTP {r.status_code}: {r.text[:200]}")
        except (requests.RequestException, ValueError) as exc:
            print(f"  ! mwapi {exc.__class__.__name__}, attempt {attempt}")
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("MediaWiki API failed after retries")


def resolve_titles(titles: list[str]) -> dict[str, str | None]:
    """English Wikipedia titles → QIDs, following normalisation and redirects. Never guesses."""
    out: dict[str, str | None] = {}
    uniq = sorted(set(titles))
    for i in range(0, len(uniq), 50):
        chunk = uniq[i:i + 50]
        data = mw_get({"action": "query", "titles": "|".join(chunk), "redirects": "1",
                       "prop": "pageprops", "ppprop": "wikibase_item"})
        q = data.get("query", {})
        norm = {n["from"]: n["to"] for n in q.get("normalized", [])}
        redir = {r["from"]: r["to"] for r in q.get("redirects", [])}
        by_title = {p["title"]: p.get("pageprops", {}).get("wikibase_item") for p in q.get("pages", [])
                    if not p.get("missing")}
        for t in chunk:
            final = norm.get(t, t)
            final = redir.get(final, final)
            out[t] = by_title.get(final)
    return out


def linked_qids(enwiki_title: str) -> set[str]:
    """QIDs of the articles an English Wikipedia article links to (redirects resolved)."""
    qids: set[str] = set()
    params = {"action": "query", "generator": "links", "titles": enwiki_title, "gplnamespace": "0",
              "gpllimit": "max", "redirects": "1", "prop": "pageprops", "ppprop": "wikibase_item"}
    cont: dict = {}
    for _ in range(20):
        data = mw_get({**params, **cont})
        for p in data.get("query", {}).get("pages", []):
            w = p.get("pageprops", {}).get("wikibase_item")
            if w:
                qids.add(w)
        if "continue" not in data:
            break
        cont = {k: v for k, v in data["continue"].items()}
    return qids


def reverse_links(seeds: list[str], props: list[str], limit: int = 2000) -> list[tuple[str, str, str]]:
    """Scoped incoming query: (source, property, seed) for statements that point AT the seeds."""
    if not seeds:
        return []
    out = []
    for i in range(0, len(seeds), 40):
        chunk = seeds[i:i + 40]
        q = ("SELECT ?x ?p ?seed WHERE { VALUES ?seed { " + " ".join(f"wd:{s}" for s in chunk) + " } "
             "VALUES ?p { " + " ".join(f"wdt:{p}" for p in props) + " } ?x ?p ?seed . } LIMIT " + str(limit))
        for r in wdqs.query(q):
            out.append((wdqs.qid(r["x"]), wdqs.qid(r["p"]), wdqs.qid(r["seed"])))
    return out
