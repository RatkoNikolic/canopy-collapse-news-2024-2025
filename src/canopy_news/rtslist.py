"""Discovery route: RTS's own section listings (`/vesti/<section>.html?position=N`).

RTS has no sitemap and is not in Media Cloud; naslovi.net carries about half of
its news. Each news section paginates back for years, 10 stories a page, newest
first, and RTS article IDs grow with time. So for each section the route finds
the pages that span the window by bisecting on page position (comparing the
story IDs on a page with the window's ID bounds), then reads every page in that
range in ascending position. New stories push older ones to later pages during
a crawl, so reading in ascending order can repeat a story but never skip one.

A listing shows no dates. Each story's day is interpolated from its ID on a
calibration of (ID, day) pairs that are already known: RTS articles from
naslovi.net (listing day) and from the documents stage (page publication time).
The fetcher replaces it with the publication time read from the article page.
Listing pages are stored in raw/ (PoliteClient), so the route rebuilds offline.
"""

from __future__ import annotations

import bisect
import glob
import re
from collections import defaultdict
from datetime import date, timedelta

import duckdb
from chrono_harness import Layout

from canopy_news.discovery import Route, discovery_root, write_rows
from canopy_news.documents import doc_dir
from canopy_news.mediacloud import canonical_url
from canopy_news.polite import PoliteClient
from canopy_news.registry import Registry

BASE = "https://www.rts.rs"
SUBDIR = "rtslist-rts"
STORY = re.compile(r'<a href="(/vesti/[a-z0-9-]+/(\d{6,8})/[^"]+\.html)" class="largeThumb"')
MARGIN_DAYS = 3  # pages read past each window edge, for the error of the ID→day calibration


def page_url(template: str, section: str, position: int) -> str:
    return template.format(section=section, position=position)


def parse_page(html: str) -> list[tuple[str, int]]:
    """(canonical article URL, story ID) of the section's own stories, in page order;
    the sidebar ("Najnovije") sits outside #storyBrowser and is ignored."""
    start = html.find('id="storyBrowser"')
    if start < 0:
        return []
    body = html[start:]
    end = body.find('aria-label="Pagination"')
    body = body[:end] if end > 0 else body
    return list(dict.fromkeys((canonical_url(BASE + path), int(sid))
                              for path, sid in STORY.findall(body)))


def calibration(lay: Layout) -> list[tuple[int, date]]:
    """(median story ID, day) per day, from RTS stories whose day is known locally:
    naslovi.net listing days and page publication times. The median per day is
    robust to the older stories naslovi.net links as "related" under a later day
    (a running maximum over raw pairs let a few of them push all of early November
    to its last week); the medians are then made non-decreasing."""
    pairs: list[tuple[int, date]] = []
    nas = glob.glob(str(discovery_root(lay) / "naslovi-rts" / "*.parquet"))
    if nas:
        pairs += duckdb.sql(f"""SELECT try_cast(regexp_extract(url, '/(\\d{{6,8}})/', 1) AS BIGINT), day
            FROM read_parquet({nas!r})""").fetchall()
    docs = sorted(doc_dir(lay).glob("part-*.parquet"))
    if docs:
        listing = ", ".join(f"'{f}'" for f in docs)
        pairs += duckdb.sql(f"""SELECT try_cast(regexp_extract(unit_id, '/(\\d{{6,8}})/', 1) AS BIGINT),
                CAST(valid_time AS DATE)
            FROM read_parquet([{listing}]) WHERE outlet_id = 'rts'""").fetchall()
    return day_medians([(i, d) for i, d in pairs if i is not None and d is not None])


def day_medians(pairs: list[tuple[int, date]]) -> list[tuple[int, date]]:
    by_day: dict[date, list[int]] = defaultdict(list)
    for i, d in pairs:
        by_day[d].append(i)
    if len(by_day) < 10:
        raise SystemExit("too few days with known RTS story IDs to date the listing: run naslovi first")
    out, best = [], 0
    for d in sorted(by_day):
        ids = sorted(by_day[d])
        best = max(best, ids[len(ids) // 2])
        out.append((best, d))
    return out


def ids_per_day(cal: list[tuple[int, date]]) -> float:
    (i0, d0), (i1, d1) = cal[0], cal[-1]
    return (i1 - i0) / max(1, (d1 - d0).days)


def day_of(cal: list[tuple[int, date]], story_id: int) -> date:
    """Day by linear interpolation between neighbouring day medians, extrapolated past
    either end at the average rate."""
    ids = [i for i, _ in cal]
    k = bisect.bisect_left(ids, story_id)
    if k == 0 or k == len(cal):
        i_ref, d_ref = cal[0] if k == 0 else cal[-1]
        return d_ref + timedelta(days=round((story_id - i_ref) / ids_per_day(cal)))
    (i0, d0), (i1, d1) = cal[k - 1], cal[k]
    frac = (story_id - i0) / (i1 - i0) if i1 != i0 else 0.0
    return date.fromordinal(round(d0.toordinal() + frac * (d1.toordinal() - d0.toordinal())))


def id_bounds(cal: list[tuple[int, date]], start: date, end: date,
              margin_days: int = MARGIN_DAYS) -> tuple[int, int]:
    """Story IDs from `margin_days` before the window to `margin_days` after it."""
    rate = ids_per_day(cal)
    lo_d, hi_d = start - timedelta(margin_days), end + timedelta(margin_days)
    before = [(i, d) for i, d in cal if d <= lo_d] or [cal[0]]
    after = [(i, d) for i, d in cal if d >= hi_d] or [cal[-1]]
    i_lo, d_lo = before[-1]
    i_hi, d_hi = after[0]
    return (round(i_lo - rate * max(0, (d_lo - lo_d).days)),
            round(i_hi + rate * max(0, (hi_d - d_hi).days)))


class Section:
    """One section's listing, with pages cached in raw/ and in memory."""

    def __init__(self, client: PoliteClient, template: str, section: str) -> None:
        self.client, self.template, self.section = client, template, section
        self.memo: dict[int, list[tuple[str, int]]] = {}

    def page(self, position: int) -> list[tuple[str, int]]:
        if position not in self.memo:
            status, body = self.client.get(page_url(self.template, self.section, position))
            self.memo[position] = parse_page(body.decode("utf-8", "replace")) if status == 200 else []
        return self.memo[position]

    def first_position(self, pred) -> int:
        """Smallest position whose page satisfies `pred` (monotone: False…False True…True);
        an empty page (past the end) counts as True."""
        hi = 1
        while not (not self.page(hi) or pred(self.page(hi))):
            hi *= 2
        lo = hi // 2
        while lo < hi:
            mid = (lo + hi) // 2
            if not self.page(mid) or pred(self.page(mid)):
                hi = mid
            else:
                lo = mid + 1
        return lo

    def window_pages(self, id_lo: int, id_hi: int) -> tuple[int, int]:
        """(first, last) positions whose stories reach into [id_lo, id_hi]."""
        first = self.first_position(lambda s: min(i for _, i in s) <= id_hi)
        after = self.first_position(lambda s: max(i for _, i in s) < id_lo)
        return first, max(first, after - 1)


def discover(lay: Layout, routes: list[Route], registry: Registry, start: date,
             end: date) -> dict:
    cal = calibration(lay)
    id_lo, id_hi = id_bounds(cal, start, end)
    client = PoliteClient(lay, index_name="rtslist")
    report: dict[str, dict] = {}
    by_day: dict[date, dict[str, dict]] = defaultdict(dict)
    try:
        for r in (r for r in routes if r.route == "listing" and r.outlet_id == "rts"
                  and registry.outlet_for("rts.rs") is not None):
            for section in r.include.split("|"):
                sec = Section(client, r.source, section)
                first, last = sec.window_pages(id_lo, id_hi)
                found = 0
                for pos in range(first, last + 1):
                    src = page_url(r.source, section, pos)
                    for url, sid in sec.page(pos):
                        if not id_lo <= sid <= id_hi:
                            continue
                        day = day_of(cal, sid)
                        if start <= day <= end:
                            found += 1
                            by_day[day].setdefault(url, {
                                "route": "rtslist", "outlet_id": "rts", "url": url,
                                "host": "www.rts.rs", "day": day, "pub_date": None,
                                "lastmod": None, "title": None, "source": src})
                report[section] = {"first_page": first, "last_page": last, "stories": found,
                                   "requests_cached": len(sec.memo)}
    finally:
        client.close()
    for day, rows in sorted(by_day.items()):
        write_rows(lay, SUBDIR, day.isoformat(), list(rows.values()))
    report["_total"] = {"urls": sum(len(v) for v in by_day.values()), "days": len(by_day),
                        "id_bounds": [id_lo, id_hi]}
    return report
