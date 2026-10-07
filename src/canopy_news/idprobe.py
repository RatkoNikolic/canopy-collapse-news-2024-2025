"""Discovery route: probe the article IDs no other route found (completeness pass).

Pink and Informer number their articles sequentially, and Media Cloud, their only
other route, holds about 98% of the window's ID range. This route lists the IDs
in that range no discovered URL carries and asks the outlet for each one through
a URL that resolves by ID (`source` in registries/discovery.csv, with `{id}`, and
`{section}` filled from `include` when the outlet needs the article's own section).
The page's canonical URL identifies the article: a known article (matched by ID,
since hosts differ in `www.`) or a redirect to the 404 page adds nothing; a new
one becomes a discovery row, dated by the page. Non-news is dropped later by the
fetcher's URL-path filter, as for every route. Probed IDs are kept in
`_probed.jsonl`, pages in raw/ (PoliteClient), so a rerun asks only for new IDs.

The ID range comes from the window's fetched articles: per-day median IDs over
page-dated documents, extended by one day at the observed rate.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date

import duckdb
from chrono_harness import Layout

from canopy_news.discovery import Route, discovery_files, discovery_root, write_rows
from canopy_news.documents import doc_dir
from canopy_news.mediacloud import canonical_url, host_of
from canopy_news.pagedate import page_published
from canopy_news.polite import Blocked, PoliteClient
from canopy_news.registry import Registry
from canopy_news.rtslist import day_medians, id_bounds

ID_IN_PATH = r"/(\d{5,8})(?:/|$)"
CANONICAL = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)')


def subdir(outlet: str) -> str:
    return f"idprobe-{outlet}"


def article_id(url: str) -> int | None:
    m = re.search(ID_IN_PATH, url or "")
    return int(m.group(1)) if m else None


def known_ids(lay: Layout, domain: str) -> set[int]:
    files = [str(f) for f in discovery_files(lay)]
    if not files:
        return set()
    rows = duckdb.sql(f"""SELECT DISTINCT try_cast(regexp_extract(url, '{ID_IN_PATH}', 1) AS BIGINT)
        FROM read_parquet({files!r}, union_by_name = true)
        WHERE url LIKE '%{domain}/%'""").fetchall()
    return {r[0] for r in rows if r[0] is not None}


def window_range(lay: Layout, outlet: str, start: date, end: date) -> tuple[int, int]:
    docs = [str(f) for f in sorted(doc_dir(lay).glob("part-*.parquet"))]
    pairs = duckdb.sql(f"""SELECT try_cast(regexp_extract(unit_id, '{ID_IN_PATH}', 1) AS BIGINT),
            CAST(valid_time AS DATE)
        FROM read_parquet({docs!r}) WHERE outlet_id = '{outlet}' AND pub_date_source = 'page'""").fetchall()
    # page dates are exact, so one day either side covers the per-day spread of IDs
    return id_bounds(day_medians([(i, d) for i, d in pairs if i is not None]), start, end, 1)


def classify(page: str, status: int) -> str | None:
    """The article's canonical URL, or None when the ID resolves to no article
    (an error status, or a 404 page, which carries no article canonical)."""
    if status != 200:
        return None
    m = CANONICAL.search(page)
    canon = canonical_url(m.group(1)) if m else None
    if canon is None or "/404" in canon or article_id(canon) is None:
        return None
    return canon


def discover(lay: Layout, routes: list[Route], registry: Registry, start: date, end: date,
             outlets: set[str] | None = None) -> dict:
    report = {}
    for r in (r for r in routes if r.route == "idprobe"):
        if outlets and r.outlet_id not in outlets:
            continue
        domain = host_of(r.source)
        if registry.outlet_for(domain) is None:
            continue
        lo, hi = window_range(lay, r.outlet_id, start, end)
        known = known_ids(lay, domain)
        out_dir = discovery_root(lay) / subdir(r.outlet_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        ledger = out_dir / "_probed.jsonl"
        probed = {json.loads(x)["id"]: json.loads(x) for x in ledger.read_text().splitlines()
                  if x.strip()} if ledger.exists() else {}
        todo = [i for i in range(lo, hi + 1) if i not in known and i not in probed]
        client = PoliteClient(lay, index_name=subdir(r.outlet_id))
        try:
            with ledger.open("a", encoding="utf-8") as fh:
                sections = [x for x in r.include.split("|") if x] or [""]
                for i in todo:
                    # an outlet that resolves IDs only under the right section (Informer) is
                    # asked section by section, most frequent first, until one answers
                    rec, canon, body = None, None, b""
                    for sec in sections:
                        url = r.source.format(id=i, section=sec)
                        try:
                            status, body = client.get(url)
                        except Blocked:
                            rec = {"id": i, "outcome": "robots"}
                            break
                        canon = classify(body.decode("utf-8", "replace"), status)
                        if canon is not None:
                            break
                    if rec is None:
                        if canon is None:
                            # with sections: no article under any listed (news) section
                            rec = {"id": i, "status": status, "tried": len(sections),
                                   "outcome": "absent" if len(sections) == 1 else "not_in_sections"}
                        elif article_id(canon) in known:
                            rec = {"id": i, "outcome": "known", "url": canon}
                        else:
                            dt = page_published(body)
                            rec = {"id": i, "outcome": "new", "url": canon,
                                   "day": dt.date().isoformat() if dt else None, "probe": url}
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
                    probed[i] = rec
        finally:
            client.close()
        by_day: dict[str, list[dict]] = defaultdict(list)
        for rec in probed.values():
            if rec["outcome"] == "new" and rec.get("day"):
                d = date.fromisoformat(rec["day"])
                if start <= d <= end:
                    by_day[rec["day"]].append({
                        "route": "idprobe", "outlet_id": r.outlet_id, "url": rec["url"],
                        "host": host_of(rec["url"]), "day": d, "pub_date": None,
                        "lastmod": None, "title": None, "source": rec["probe"]})
        for f in out_dir.glob("*.parquet"):
            f.unlink()
        for day, rows in by_day.items():
            write_rows(lay, subdir(r.outlet_id), day, rows)
        outcomes = defaultdict(int)
        for rec in probed.values():
            outcomes[rec["outcome"]] += 1
        report[r.outlet_id] = {"id_range": [lo, hi], "range_size": hi - lo + 1,
                               "known": sum(lo <= k <= hi for k in known),
                               "probed_now": len(todo), **outcomes,
                               "new_in_window": sum(len(v) for v in by_day.values())}
    return report
