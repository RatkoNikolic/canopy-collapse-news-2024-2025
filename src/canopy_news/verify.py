"""Verify a sample of stored articles against the live web.

For a seeded random sample of current documents per outlet, the article URL is
fetched again (robots.txt, the project user agent, ≥ 2 s per host, one worker
per host), extracted with the current extractor and compared with the stored
record by the hash of the normalised body:

- unchanged — same body hash;
- edited — the page answers but the text differs (similarity ratio reported);
- gone — 404 / 410;
- failed — any other status, robots refusal or network error.

This is what a reviewer runs against the release's URLs and body hashes: the web
moves, so a rerun cannot reproduce the corpus byte for byte, but it can show how
much of it still stands. It refuses to run while a fetch pass is running, so the
two never share a host's request budget. Report: builds/verify/<UTC time>.json.
"""

from __future__ import annotations

import difflib
import json
import random
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import duckdb
from chrono_harness import Layout
from chrono_harness.timeutil import now_utc

from canopy_news.documents import doc_dir, extract, load_rules
from canopy_news.polite import Blocked, PoliteClient

GONE = {404, 410}


def sample(lay: Layout, per_outlet: int, seed: int, outlets: set[str] | None) -> list[dict]:
    docs = [str(f) for f in sorted(doc_dir(lay).glob("part-*.parquet"))]
    rows = duckdb.sql(f"""SELECT event_id, unit_id, outlet_id, body_hash, body
        FROM read_parquet({docs!r}) WHERE error IS NULL AND n_chars >= 200
        ORDER BY event_id""").to_arrow_table().to_pylist()
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if outlets is None or r["outlet_id"] in outlets:
            by[r["outlet_id"]].append(r)
    rng = random.Random(seed)
    return [r for o in sorted(by) for r in rng.sample(by[o], min(per_outlet, len(by[o])))]


def compare(stored: dict, status: int, body: bytes, rules: dict) -> dict:
    out = {"event_id": stored["event_id"], "url": stored["unit_id"],
           "outlet_id": stored["outlet_id"], "status": status}
    if status in GONE:
        return out | {"outcome": "gone"}
    if status != 200:
        return out | {"outcome": "failed"}
    new = extract(body, stored["unit_id"], rules)
    if new["body_hash"] == stored["body_hash"]:
        return out | {"outcome": "unchanged"}
    ratio = difflib.SequenceMatcher(None, stored["body"], new["body"], autojunk=False).ratio()
    return out | {"outcome": "edited", "similarity": round(ratio, 4)}


def run(lay: Layout, *, per_outlet: int = 20, seed: int = 20261005,
        outlets: set[str] | None = None) -> dict:
    busy = subprocess.run(["pgrep", "-f", "[b]in/canopy-news fetch"], capture_output=True)
    if busy.returncode == 0:
        raise SystemExit("a fetch pass is running: verify after it ends (shared per-host budget)")
    rules = load_rules()
    picked = sample(lay, per_outlet, seed, outlets)
    by_host: dict[str, list[dict]] = defaultdict(list)
    for r in picked:
        by_host[urlsplit(r["unit_id"]).hostname or ""].append(r)

    def worker(items: list[dict]) -> list[dict]:
        client = PoliteClient(lay, index_name="verify")
        res = []
        try:
            for r in items:
                try:
                    status, body = client.get(r["unit_id"], use_cache=False)
                except Blocked:
                    res.append({"event_id": r["event_id"], "url": r["unit_id"],
                                "outlet_id": r["outlet_id"], "outcome": "failed",
                                "status": None, "note": "robots"})
                    continue
                res.append(compare(r, status, body, rules.get(r["outlet_id"], {})))
        finally:
            client.close()
        return res

    with ThreadPoolExecutor(max_workers=max(1, len(by_host))) as pool:
        results = [x for part in pool.map(worker, by_host.values()) for x in part]
    summary: dict[str, Counter] = defaultdict(Counter)
    for x in results:
        summary[x["outlet_id"]][x["outcome"]] += 1
    report = {"at": now_utc().isoformat(), "per_outlet": per_outlet, "seed": seed,
              "summary": {o: dict(c) for o, c in sorted(summary.items())},
              "results": results}
    out = lay.build_dir("verify")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{now_utc().strftime('%Y%m%dT%H%M%SZ')}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    return {k: report[k] for k in ("at", "per_outlet", "seed", "summary")}
