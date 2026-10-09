"""Rebuild the article texts from the released index (PROTOCOL.md §7).

    canopy-news hydrate --index index.parquet [--scope scope.parquet --in-scope-only]
                        [--outlets n1,rts] [--limit N] [--out texts/]

The release carries no text. For every article in the index (status `article`) this fetches
the URL politely (robots.txt incl. Crawl-delay, ≥ 2 s per host, the project user agent, one
worker per host), extracts the text with the dataset's extractor, and compares the result
with the released `body_sha256`:

- matched — the same text as collected;
- changed — the page answers but the outlet has since edited the text (kept, flagged);
- gone — 404 / 410;
- failed — any other status, a robots refusal or a network error.

Output: one JSON line per article in <out>/<host>.jsonl (event_id, url, outlet_id, outcome,
expected and found hash, title, lead, body, fetched_at). The run resumes: articles already in
the output are skipped. The texts are the outlets' copyright: keep them for your research and
never redistribute them. Fetched pages are also stored under raw/, so a rerun reads them back
without a request.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
from chrono_harness import Layout
from chrono_harness.timeutil import now_utc

from canopy_news.documents import extract, load_rules
from canopy_news.polite import Blocked, PoliteClient

GONE = {404, 410}


def targets(index: Path, scope: Path | None = None, *, in_scope_only: bool = False,
            outlets: set[str] | None = None, limit: int | None = None) -> list[dict]:
    if in_scope_only and scope is None:
        raise SystemExit("--in-scope-only needs --scope scope.parquet")
    join = (f"JOIN read_parquet('{scope}') s USING (event_id) WHERE s.in_scope AND"
            if in_scope_only else "WHERE")
    rows = duckdb.sql(f"""SELECT i.event_id, i.url, i.outlet_id, i.body_sha256
        FROM read_parquet('{index}') i {join} i.status = 'article'
        ORDER BY i.event_id""").to_arrow_table().to_pylist()
    rows = [r for r in rows if outlets is None or r["outlet_id"] in outlets]
    return rows[:limit] if limit is not None else rows


def check(row: dict, status: int, page: bytes, rules: dict) -> dict:
    out = {"event_id": row["event_id"], "url": row["url"], "outlet_id": row["outlet_id"],
           "status": status, "expected_hash": row["body_sha256"], "found_hash": None,
           "title": None, "lead": None, "body": None, "fetched_at": now_utc().isoformat()}
    if status in GONE:
        return out | {"outcome": "gone"}
    if status != 200:
        return out | {"outcome": "failed"}
    doc = extract(page, row["url"], rules)
    return out | {"outcome": "matched" if doc["body_hash"] == row["body_sha256"] else "changed",
                  "found_hash": doc["body_hash"], "title": doc["title"], "lead": doc["lead"],
                  "body": doc["body"]}


def _done(out: Path) -> set[str]:
    return {json.loads(x)["event_id"] for f in out.glob("*.jsonl")
            for x in f.read_text(encoding="utf-8").splitlines() if x.strip()}


def run(lay: Layout, index: Path, *, out: Path, scope: Path | None = None,
        in_scope_only: bool = False, outlets: set[str] | None = None,
        limit: int | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    done = _done(out)
    todo = [r for r in targets(index, scope, in_scope_only=in_scope_only, outlets=outlets,
                               limit=limit) if r["event_id"] not in done]
    rules = load_rules()
    by_host: dict[str, list[dict]] = defaultdict(list)
    for r in todo:
        by_host[urlsplit(r["url"]).hostname or ""].append(r)

    def worker(host: str, items: list[dict]) -> Counter:
        client = PoliteClient(lay, index_name="hydrate")
        counts: Counter = Counter()
        try:
            with (out / f"{host}.jsonl").open("a", encoding="utf-8") as fh:
                for r in items:
                    try:
                        status, page = client.get(r["url"])
                        res = check(r, status, page, rules.get(r["outlet_id"], {}))
                    except Blocked:
                        res = check(r, 0, b"", {}) | {"outcome": "failed", "note": "robots"}
                    fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                    fh.flush()
                    counts[res["outcome"]] += 1
        finally:
            client.close()
        return counts

    with ThreadPoolExecutor(max_workers=max(1, len(by_host))) as pool:
        parts = list(pool.map(lambda kv: worker(*kv), by_host.items()))
    total: Counter = Counter()
    for c in parts:
        total.update(c)
    return {"out": str(out), "already_done": len(done), "this_run": dict(total),
            "articles": len(done) + sum(total.values())}
