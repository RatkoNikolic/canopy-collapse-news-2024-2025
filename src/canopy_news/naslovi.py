"""Discovery route: naslovi.net, for outlets with neither sitemaps nor
Media Cloud coverage (RTS, B92).

naslovi.net lists each source's items per day at
`/YYYY-MM-DD/izvor/<slug>/` (paginated `/2`, `/3`, …). An item page links to
the original article with a "source" button (`class="src-btn"`), so
resolving costs one request per article. Section listings
(`/YYYY-MM-DD/izvor/<slug>/<section>/`) are supported through `include`, but
they do not paginate and lose items, so the routes in registries/discovery.csv
read the full listing; non-news is dropped later by the original URL's path.
Listing and item pages are stored
in raw/, so the route can be rebuilt without asking the site again. A day
already written is skipped unless `refresh`.
"""

from __future__ import annotations

import re
from datetime import date

from chrono_harness import Layout

from canopy_news.discovery import Route, discovery_root, write_rows
from canopy_news.mediacloud import canonical_url, days, host_of
from canopy_news.polite import Blocked, PoliteClient
from canopy_news.registry import Registry

BASE = "https://naslovi.net"
SRC_BTN = re.compile(
    r"""<a\s+href=(['"])(?P<url>https?://[^'"]+)\1[^>]*class=["'][^"']*\bsrc-btn\b""")


def listing_url(day: date, slug: str, page: int = 1, section: str | None = None) -> str:
    path = f"{BASE}/{day.isoformat()}/izvor/{slug}/" + (f"{section}/" if section else "")
    return path + (str(page) if page > 1 else "")


def parse_listing(html: str, day: date, slug: str,
                  section: str | None = None) -> tuple[list[str], int]:
    """(item page URLs in page order, highest page number linked)."""
    # main items use double quotes; the related same-outlet items listed under
    # each one ("a-threads") use single quotes: both count
    item_re = re.compile(
        rf"""href=["']({re.escape(BASE)}/{day.isoformat()}/{re.escape(slug)}/[^"'/]+/\d+)["']""")
    items = list(dict.fromkeys(item_re.findall(html)))
    prefix = f"izvor/{re.escape(slug)}/" + (f"{re.escape(section)}/" if section else "")
    pages = [int(p) for p in re.findall(rf'{prefix}(\d+)"', html)]
    return items, max(pages, default=1)


def parse_item(html: str) -> str | None:
    m = SRC_BTN.search(html)
    return m.group("url") if m else None


class Transient(Exception):
    """A listing or item request failed in a way worth retrying (429, 5xx, network):
    the day is not written, so the next run redoes it."""


def _day_rows(client: PoliteClient, route: Route, registry: Registry, day: date,
              counts: dict[str, int]) -> list[dict]:
    rows, seen = [], set()
    for section in [x for x in route.include.split("|") if x] or [None]:
        page, last_page = 1, 1
        while page <= last_page:
            status, body = client.get(listing_url(day, route.source, page, section))
            if status == 404:
                break
            if status != 200:
                raise Transient(f"listing {status}")
            items, last_page = parse_listing(body.decode("utf-8", "replace"), day,
                                             route.source, section)
            for item in items:
                if item in seen:
                    continue
                seen.add(item)
                counts["items"] += 1
                st, item_body = client.get(item)
                if st not in (200, 404):
                    raise Transient(f"item {st}")
                original = parse_item(item_body.decode("utf-8", "replace")) if st == 200 else None
                if original is None:
                    counts["unresolved"] += 1
                    continue
                canon = canonical_url(original)
                outlet = registry.outlet_for(host_of(canon))
                if outlet is None or outlet.outlet_id != route.outlet_id:
                    continue
                rows.append({"route": "naslovi", "outlet_id": route.outlet_id, "url": canon,
                             "host": host_of(canon), "day": day, "pub_date": None,
                             "lastmod": None, "title": None, "source": item})
            page += 1
    return rows


def discover(lay: Layout, routes: list[Route], registry: Registry, start: date, end: date,
             *, refresh: bool = False) -> dict[str, dict[str, int]]:
    client = PoliteClient(lay, index_name="naslovi")
    out: dict[str, dict[str, int]] = {}
    try:
        for route in (r for r in routes if r.route == "naslovi"):
            counts = {"days": 0, "items": 0, "rows": 0, "unresolved": 0, "skipped_days": 0,
                      "retry_later": 0}
            subdir = f"naslovi-{route.outlet_id}"
            for day in days(start, end):
                if not refresh and (discovery_root(lay) / subdir / f"{day}.parquet").exists():
                    counts["skipped_days"] += 1
                    continue
                try:
                    rows = _day_rows(client, route, registry, day, counts)
                except Blocked:
                    counts["blocked"] = 1
                    break
                except Transient:
                    counts["retry_later"] += 1  # pages fetched so far stay cached
                    continue
                write_rows(lay, subdir, day.isoformat(), rows)  # one file per finished day
                counts["days"] += 1
                counts["rows"] += len(rows)
            out[route.outlet_id] = counts
    finally:
        client.close()
    return out
