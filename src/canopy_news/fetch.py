"""The fetcher: one polite pass over a window's candidate URLs.

A pass is a chrono-harness run (kind="collection"). For each URL of a
registry outlet whose publication date falls in the window and that has no
event in the log yet:

- 200 + HTML  → raw/ snapshot + an `insert` event
                (valid_time = publication time, ingest_time = fetch time);
- 404 / 410   → a `delete` event (gone at fetch; the only deletion signal v1 has);
- anything else (5xx, timeouts, robots-disallowed, non-HTML) → only a row in
  the run's fetch_attempts table, so the next pass retries it.

Every attempt is a row in runs/<pass>/fetch_attempts.parquet: that table is
the coverage ledger. One worker per host, each with
its own minimum interval and its own log shard (no shared writer).
"""

from __future__ import annotations

import threading
import time
import urllib.robotparser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, time as dtime

import duckdb
import httpx
from chrono_harness import Event, EventLog, Layout, RawStore, Run, RunManifest
from chrono_harness.timeutil import now_utc

from canopy_news.config import CORPUS, USER_AGENT, Window
from canopy_news.discovery import discovery_files
from canopy_news.nonnews import NonNews
from canopy_news.documents import soft_404
from canopy_news.pagedate import page_published
from canopy_news.registry import Registry

MAX_BYTES = 8 * 1024 * 1024
HTML_TYPES = ("text/html", "application/xhtml+xml")


@dataclass(frozen=True)
class Candidate:
    url: str
    host: str
    outlet_id: str
    valid_time: datetime
    pub_date_source: str  # "rss" | "discovery_day" (refined to "page" at fetch time)
    title: str
    routes: str = ""


def candidates(lay: Layout, window: Window, registry: Registry,
               skip: set[str]) -> list[Candidate]:
    files = discovery_files(lay)
    if not files:
        return []
    listing = ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone = 'UTC'")
        # union of every route's tables
        rows = con.execute(
            f"""
            SELECT url, any_value(host) AS host,
                   min(pub_date) AS pub_date, min(day) AS day, any_value(title) AS title,
                   string_agg(DISTINCT route, ',') AS routes
            FROM read_parquet([{listing}], union_by_name = true)
            GROUP BY url
            HAVING coalesce(CAST(min(pub_date) AS DATE), min(day)) BETWEEN ? AND ?
            """,
            [window.start, window.end],
        ).to_arrow_table().to_pylist()
    finally:
        con.close()
    out = []
    for r in rows:
        if r["url"] in skip:
            continue
        outlet = registry.outlet_for(r["host"])
        if outlet is None:
            continue
        if r["pub_date"] is not None:
            valid, source = r["pub_date"], "rss"
        else:
            valid, source = datetime.combine(r["day"], dtime.min, tzinfo=UTC), "discovery_day"
        out.append(Candidate(r["url"], r["host"], outlet.outlet_id, valid, source,
                             r["title"] or "", r["routes"] or ""))
    return out


class _Robots:
    """robots.txt per host: 2xx → obey it; other 4xx → allow; 401/403, 5xx or
    no answer → treat the host as closed for this pass."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def parser(self, host: str) -> urllib.robotparser.RobotFileParser | None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = self.client.get(f"https://{host}/robots.txt")
        except httpx.HTTPError:
            return None
        if resp.status_code in (401, 403) or resp.status_code >= 500:
            return None
        rp.parse(resp.text.splitlines() if resp.status_code < 300 else [])
        return rp


def _retry_after(value: str | None, default: float = 60.0) -> float:
    try:
        return min(max(float(value), 5.0), 900.0) if value else default
    except ValueError:
        return default


def _get(client: httpx.Client, url: str) -> tuple[int, str, str, bytes, bool, float | None]:
    """GET with a size cap: (status, final_url, content_type, body, truncated, retry_after).
    `retry_after` is set when the server answers 429 or 503."""
    with client.stream("GET", url) as resp:
        body, truncated = bytearray(), False
        for chunk in resp.iter_bytes():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                truncated = True
                break
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        wait = (_retry_after(resp.headers.get("retry-after"))
                if resp.status_code in (429, 503) else None)
        return resp.status_code, str(resp.url), ctype, bytes(body), truncated, wait


RECOVER_AFTER = 25  # successes in a row before a throttled host's interval eases by 1/1.25


def run_pass(lay: Layout, window: Window, registry: Registry, *, limit: int | None = None,
             min_interval_s: float = 2.0, max_hosts: int = 32,
             batch: int = 50) -> Run:
    if not registry.outlets:
        raise SystemExit(
            "registries/outlets.csv is empty: fill it by the outlet rule in PROTOCOL.md §2 "
            "before fetching anything."
        )
    log = EventLog(lay.log)
    store = RawStore(lay.raw)
    nonnews = NonNews.load()
    found = candidates(lay, window, registry, skip=log.unit_ids(CORPUS))
    todo, excluded = [], {}
    for c in found:  # non-news sections are never fetched (PROTOCOL.md §3.2)
        why = nonnews.reason(c.outlet_id, c.url)
        if why is None:
            todo.append(c)
        else:
            excluded[c.outlet_id] = excluded.get(c.outlet_id, 0) + 1
    if limit is not None:
        todo = todo[:limit]
    by_host: dict[str, list[Candidate]] = defaultdict(list)
    for c in todo:
        by_host[c.host].append(c)

    manifest = RunManifest(
        kind="collection", corpus=CORPUS,
        params={"window": window.name, "window_start": window.start.isoformat(),
                "window_end": window.end.isoformat(), "evaluate": window.evaluate,
                "candidates": len(todo), "hosts": len(by_host),
                "excluded_nonnews": excluded,
                "min_interval_s": min_interval_s, "registry_rules": registry.rules_version,
                "feeds": sorted({r for c in todo for r in c.routes.split(",") if r}),
                "user_agent": USER_AGENT},
        data_hashes={"log_before": log.fingerprint()},
    )
    run = Run(lay.runs, manifest, label=f"fetch-{window.name}")
    lock = threading.Lock()

    def attempt(**row) -> None:
        with lock:
            run.record("fetch_attempts", **row)

    def worker(host: str, items: list[Candidate]) -> int:
        client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30,
                              follow_redirects=True)
        events: list[Event] = []
        shard = f"{run.run_id}-{host.replace('.', '_')}"
        try:
            rp = _Robots(client).parser(host)
            delay = rp.crawl_delay(USER_AGENT) if rp is not None else None
            base_interval = max(min_interval_s, float(delay or 0))  # Crawl-delay wins if longer
            interval, streak, last = base_interval, 0, 0.0
            for c in items:
                base = {"url": c.url, "host": host, "outlet_id": c.outlet_id,
                        "attempted_at": now_utc()}
                if rp is None or not rp.can_fetch(USER_AGENT, c.url):
                    attempt(**base, outcome="robots_closed" if rp is None else "robots_disallow")
                    continue
                wait = interval - (time.monotonic() - last)
                if wait > 0:
                    time.sleep(wait)
                last = time.monotonic()
                try:
                    status, final_url, ctype, body, truncated, retry = _get(client, c.url)
                    if retry is not None:  # the host asks us to slow down: wait, then go slower
                        attempt(**base, outcome="throttled", status=status)
                        time.sleep(retry)
                        interval, streak = min(interval * 1.5, 30.0), 0
                        last = time.monotonic()
                        status, final_url, ctype, body, truncated, retry = _get(client, c.url)
                    elif status == 200:  # recover gradually, never below the base interval
                        streak += 1
                        if streak >= RECOVER_AFTER and interval > base_interval:
                            interval, streak = max(base_interval, interval / 1.25), 0
                except httpx.HTTPError as exc:
                    attempt(**base, outcome="error", error=f"{type(exc).__name__}: {exc}")
                    continue
                fetched = now_utc()
                row = {**base, "status": status, "final_url": final_url,
                       "content_type": ctype, "bytes": len(body), "truncated": truncated}
                common = {"corpus": CORPUS, "unit_id": c.url, "ingest_time": fetched,
                          "pass_id": run.run_id}
                soft = status == 200 and soft_404(c.url, final_url)
                if soft:  # a removed article answered with a section page: recorded as gone
                    status = 404
                if status == 200 and ctype in HTML_TYPES and not truncated:
                    sha = store.put(body)
                    declared = page_published(body)  # the page's own date wins
                    events.append(Event.make(
                        kind="insert", valid_time=declared or c.valid_time, content_sha256=sha,
                        attrs={"outlet_id": c.outlet_id, "final_url": final_url,
                               "pub_date_source": "page" if declared else c.pub_date_source,
                               "discovery_date": c.valid_time.isoformat(), "title": c.title,
                               "discovered_via": c.routes, "window": window.name},
                        **common))
                    attempt(**row, outcome="stored", sha256=sha)
                elif status in (404, 410):
                    events.append(Event.make(
                        kind="delete", valid_time=fetched,
                        attrs={"outlet_id": c.outlet_id,
                               "reason": "redirected_to_listing" if soft else "gone_at_fetch",
                               "status": status, "published": c.valid_time.isoformat(),
                               "window": window.name},
                        **common))
                    attempt(**row, outcome="gone")
                else:
                    attempt(**row, outcome="skipped")
                if len(events) >= batch:
                    log.append(events, shard=shard)
                    events = []
                    with lock:  # the coverage ledger survives a stopped pass
                        run.flush()
            return len(items)
        finally:
            if events:
                log.append(events, shard=shard)
            client.close()

    with run:
        with ThreadPoolExecutor(max_workers=max_hosts) as pool:
            for future in [pool.submit(worker, h, items) for h, items in by_host.items()]:
                future.result()
        run.manifest.data_hashes["log_after"] = log.fingerprint()
    return run
