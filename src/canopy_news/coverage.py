"""Coverage check (M1): what the corpus holds per outlet and day, against what
the outlets publish.

Per outlet × day of the window:
- `discovered`: news URLs found by any discovery route (non-news excluded);
- `fetched`: articles stored (the latest insert per article), dated by the page itself;
- `dated_out`: stored, but the page dates them outside the window (counted on the discovery day, not in the corpus);
- `gone`: URLs that returned 404/410 at fetch;
- `failed`: URLs whose latest attempt failed (error, robots, non-HTML), retried by the next pass;
- `expected`: news articles per day measured on 2026-10-02 from sitemaps, sequential
  article IDs, Media Cloud and naslovi.net, after the non-news share (EXPECTED_PER_DAY).

Written to builds/coverage/<window>.parquet; `summary` aggregates per outlet.
"""

from __future__ import annotations

import glob
import json
from collections import defaultdict
from datetime import date, timedelta

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import EventLog, Layout

from canopy_news.documents import soft_404

from canopy_news.config import CORPUS, Window
from canopy_news.fetch import candidates
from canopy_news.nonnews import NonNews
from canopy_news.registry import Registry

# news articles per day, from the 2026-10-02 volume measurement × (1 − non-news share)
EXPECTED_PER_DAY = {"n1": 118, "blic": 195, "telegraf": 170, "danas": 124, "nova": 105,
                    "rts": 60, "b92": 154, "informer": 200, "pink": 150}


def table(lay: Layout, window: Window, registry: Registry) -> list[dict]:
    nonnews = NonNews.load()
    found = [c for c in candidates(lay, window, registry, skip=set())
             if nonnews.reason(c.outlet_id, c.url) is None]
    cells: dict[tuple[str, date], dict] = defaultdict(
        lambda: {"discovered": 0, "fetched": 0, "dated_out": 0, "gone": 0, "failed": 0})
    by_url = {}
    for c in found:
        cells[(c.outlet_id, c.valid_time.date())]["discovered"] += 1
        by_url[c.url] = (c.outlet_id, c.valid_time.date())

    events = EventLog(lay.log).connect().execute(
        "SELECT kind, unit_id, CAST(CAST(valid_time AS DATE) AS VARCHAR) d, attrs FROM events "
        "WHERE corpus = ? "
        # one insert per article: a date correction (redate.py) is a later insert of the unit
        "QUALIFY kind <> 'insert' OR row_number() OVER ("
        "PARTITION BY unit_id, kind ORDER BY ingest_time DESC, event_id DESC) = 1",
        [CORPUS]).fetchall()
    done = set()
    for kind, unit, d, _attrs in events:
        if unit not in by_url:
            continue
        outlet, disc_day = by_url[unit]
        done.add(unit)
        if kind == "insert" and soft_404(unit, json.loads(_attrs or "{}").get("final_url")):
            cells[(outlet, disc_day)]["gone"] += 1  # stored a section page: the article is gone
        elif kind == "insert":
            day = date.fromisoformat(d)
            if window.contains(day):
                cells[(outlet, day)]["fetched"] += 1
            else:  # fetched, but the page dates it outside the window: not in the corpus
                cells[(outlet, disc_day)]["dated_out"] += 1
        elif kind == "delete":
            cells[(outlet, disc_day)]["gone"] += 1

    files = glob.glob(str(lay.runs / "*fetch*" / "fetch_attempts.parquet"))
    if files:
        latest = duckdb.sql(f"""SELECT url, arg_max(outcome, attempted_at) AS outcome
            FROM read_parquet({files}, union_by_name = true) GROUP BY url""").fetchall()
        for url, outcome in latest:
            if url in by_url and url not in done and outcome not in ("stored", "gone"):
                outlet, disc_day = by_url[url]
                cells[(outlet, disc_day)]["failed"] += 1

    rows = []
    day = window.start
    while day <= window.end:
        for outlet in sorted(EXPECTED_PER_DAY):
            if registry.outlet_for(next(iter(
                    o.domains for o in registry.outlets if o.outlet_id == outlet), ("",))[0]) is None:
                continue
            c = cells[(outlet, day)]
            rows.append({"outlet_id": outlet, "day": day, **c,
                         "expected": EXPECTED_PER_DAY[outlet]})
        day += timedelta(days=1)
    return rows


def write(lay: Layout, window: Window, rows: list[dict]) -> None:
    out = lay.build_dir("coverage")
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), out / f"{window.name}.parquet")


def summary(rows: list[dict]) -> dict[str, dict]:
    agg: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        a = agg[r["outlet_id"]]
        for k in ("discovered", "fetched", "dated_out", "gone", "failed", "expected"):
            a[k] += r[k]
        a["days"] += 1
        a["days_without_discovery"] += r["discovered"] == 0
    out = {}
    for outlet, a in sorted(agg.items()):
        out[outlet] = {**a, "discovered_vs_expected": round(a["discovered"] / a["expected"], 2),
                       "fetched_share": round(a["fetched"] / a["discovered"], 3)
                       if a["discovered"] else 0.0}
    return out
