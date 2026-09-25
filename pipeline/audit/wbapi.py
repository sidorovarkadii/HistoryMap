"""Minimal Wikidata Action API client (wbgetentities) for the Milestone 1 audit.

THROWAWAY (audit harness). Why not SPARQL for details: WDQS enforces a per-client query-time quota
(HTTP 429 after heavy detail joins, observed 2026-09-24), while entity JSON gives exactly what §4.6
provenance needs — statement GUIDs, ranks, qualifiers, references, sitelinks, lastrevid — with time
values in their SOURCE calendar (WDQS converts day-precision Julian values to Gregorian).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

from wdqs import USER_AGENT, ROOT

ENDPOINT = "https://www.wikidata.org/w/api.php"
CACHE_DIR = ROOT / "pipeline" / "cache" / "wbapi"
stats = {"hits": 0, "requests": 0}
_last = 0.0


def get_entities(qids: list[str], props: str = "labels|descriptions|claims|sitelinks|info") -> dict[str, dict]:
    """Fetch up to 50 entities; cached per (sorted ids, props)."""
    ids = "|".join(sorted(set(qids)))
    key = hashlib.sha256(f"{ids}#{props}".encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        stats["hits"] += 1
        return json.loads(path.read_text(encoding="utf-8"))
    params = {"action": "wbgetentities", "ids": ids, "props": props, "languages": "en",
              "format": "json", "formatversion": "2", "maxlag": "5"}
    global _last
    delay = 5.0
    for attempt in range(1, 13):
        wait = 1.0 - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
        stats["requests"] += 1
        try:
            r = requests.get(ENDPOINT, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
        except requests.RequestException as exc:
            print(f"  ! wbapi network error ({exc.__class__.__name__}), attempt {attempt}")
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 200:
            data = r.json()
            if data.get("error", {}).get("code") == "maxlag":
                # Query-service lag is folded into maxlag to slow EDITING bots; a read-only
                # wbgetentities does not touch WDQS, so retry this read without maxlag.
                # Database replication lag (which does affect reads) still backs off below.
                if data["error"].get("type") == "wikibase-queryservice" and "maxlag" in params:
                    print(f"  ! wbapi maxlag is query-service lag ({data['error'].get('lag', '?')}s) — read-only, retrying without maxlag")
                    params = {k: v for k, v in params.items() if k != "maxlag"}
                    continue
                lag = max(float(r.headers.get("Retry-After", 5)), delay)
                print(f"  ! wbapi maxlag ({data['error'].get('lag', '?')}s lag), sleeping {lag:.0f}s")
                time.sleep(lag)
                delay = min(delay * 1.5, 60)
                continue
            if "error" in data:
                raise RuntimeError(f"wbgetentities error: {data['error']}")
            ents = data.get("entities", {})
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(ents, ensure_ascii=False), encoding="utf-8")
            return ents
        if r.status_code in (429, 500, 502, 503, 504):
            ra = r.headers.get("Retry-After")
            sleep_for = float(ra) if ra and ra.isdigit() else delay
            print(f"  ! wbapi HTTP {r.status_code}, sleeping {sleep_for:.0f}s")
            time.sleep(sleep_for)
            delay *= 2
            continue
        raise RuntimeError(f"wbgetentities HTTP {r.status_code}: {r.text[:300]}")
    raise RuntimeError("wbgetentities failed after retries")
