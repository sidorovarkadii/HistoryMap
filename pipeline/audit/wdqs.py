"""Minimal Wikidata Query Service client for the Milestone 1 audit.

THROWAWAY (audit harness): not the production fetcher, but it follows the same rules --
content-addressed cache, serialized requests, backoff honouring Retry-After.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

ENDPOINT = "https://query.wikidata.org/sparql"
ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "pipeline" / "cache" / "wdqs"

_contact = os.environ.get("HM_CONTACT", "").strip()
USER_AGENT = "HistoryMap-audit/0.1 (personal research prototype" + (f"; {_contact}" if _contact else "") + ")"

stats = {"hits": 0, "requests": 0}
_last_request = 0.0
MIN_INTERVAL = 1.0  # seconds between live requests


def _key(query: str) -> str:
    return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()


def cache_path(query: str) -> Path:
    return CACHE_DIR / f"{_key(query)}.json"


def query(sparql: str, *, retries: int = 5, timeout: int = 70) -> list[dict]:
    """Run a SPARQL query; return the list of bindings (each a {var: value-string} dict)."""
    path = cache_path(sparql)
    if path.exists():
        stats["hits"] += 1
        data = json.loads(path.read_text(encoding="utf-8"))
        return _flatten(data)

    global _last_request
    delay = 5.0
    for attempt in range(1, retries + 1):
        wait = MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        stats["requests"] += 1
        try:
            r = requests.post(
                ENDPOINT,
                data={"query": sparql},
                headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            print(f"  ! network error ({exc.__class__.__name__}), attempt {attempt}/{retries}")
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 200:
            # WDQS can send 200 and then truncate the body when the query times out mid-stream:
            # parse BEFORE caching, and treat a truncated body as a timeout.
            try:
                data = r.json()
            except ValueError:
                print(f"  ! truncated response (server-side timeout), attempt {attempt}/{retries}")
                time.sleep(delay)
                delay *= 2
                continue
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(r.text, encoding="utf-8")
            return _flatten(data)
        if r.status_code in (429, 500, 502, 503, 504):
            ra = r.headers.get("Retry-After")
            sleep_for = float(ra) if ra and ra.isdigit() else delay
            print(f"  ! HTTP {r.status_code}, sleeping {sleep_for:.0f}s (attempt {attempt}/{retries})")
            time.sleep(sleep_for)
            delay *= 2
            continue
        raise RuntimeError(f"WDQS HTTP {r.status_code}: {r.text[:500]}")
    raise RuntimeError(f"WDQS failed after {retries} attempts")


def _flatten(data: dict) -> list[dict]:
    out = []
    for b in data["results"]["bindings"]:
        out.append({k: v["value"] for k, v in b.items()})
    return out


def qid(uri: str) -> str:
    """'http://www.wikidata.org/entity/Q42' -> 'Q42' (also works for statement URIs)."""
    return uri.rsplit("/", 1)[-1]
