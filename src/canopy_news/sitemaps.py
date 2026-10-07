"""Discovery route: the outlets' own sitemaps (registries/discovery.csv).

Two layouts occur among the evaluation outlets:
- **monthly** children (Blic `...by-month-2025-1.xml.gz`, Telegraf
  `/xml/sitemap/2025/m1`): the month in the URL selects the children to read,
  and that month is the item's `day` (its first day);
- **paginated** children in date order (N1 and Nova newest first, Danas oldest
  first, about a week per page): pages are bisected on their median `lastmod`
  to find the range that covers the window, plus one page on each side.
  `lastmod` can be a later edit date, so the page median, not each URL's
  lastmod, dates its URLs; the article page gives the exact date at fetch.
"""

from __future__ import annotations

import gzip
import hashlib
import re
import statistics
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime

from chrono_harness import Layout

from canopy_news.discovery import Route, write_rows
from canopy_news.mediacloud import canonical_url, host_of
from canopy_news.polite import Blocked, PoliteClient
from canopy_news.registry import Registry

MONTH_RE = re.compile(r"(\d{4})[-/]m?(\d{1,2})(?=\D*$|\.xml)")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ts(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)


def parse_sitemap(body: bytes) -> tuple[str, list[dict]]:
    """('index' | 'urlset', entries). Entries: loc, lastmod, pub_date, title."""
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    root = ET.fromstring(body)
    kind = "index" if _local(root.tag) == "sitemapindex" else "urlset"
    entries = []
    for node in root:
        fields = {"loc": None, "lastmod": None, "pub_date": None, "title": None}
        for child in node.iter():
            name = _local(child.tag)
            if name == "loc" and fields["loc"] is None:
                fields["loc"] = (child.text or "").strip()
            elif name == "lastmod":
                fields["lastmod"] = _ts(child.text)
            elif name == "publication_date":
                fields["pub_date"] = _ts(child.text)
            elif name == "title":
                fields["title"] = (child.text or "").strip()
        if fields["loc"]:
            entries.append(fields)
    return kind, entries


def child_month(url: str) -> date | None:
    m = MONTH_RE.search(url)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    return date(year, month, 1) if 1990 <= year <= 2100 and 1 <= month <= 12 else None


def _month_overlaps(month: date, start: date, end: date) -> bool:
    nxt = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return month <= end and nxt > start


def _median_day(entries: list[dict]) -> date | None:
    stamps = sorted(e["lastmod"] for e in entries if e["lastmod"])
    return statistics.median_low(stamps).date() if stamps else None


class _Pages:
    """Lazily fetched, parsed paginated children, with their median day."""

    def __init__(self, client: PoliteClient, urls: list[str]) -> None:
        self.client, self.urls, self._cache = client, urls, {}

    def get(self, i: int) -> tuple[list[dict], date | None]:
        if i not in self._cache:
            status, body = self.client.get(self.urls[i])
            entries = parse_sitemap(body)[1] if status == 200 and body else []
            self._cache[i] = (entries, _median_day(entries))
        return self._cache[i]


def _paginated_range(pages: _Pages, start: date, end: date) -> range:
    # trailing (or leading) pages can be empty: bisect over the dated span only
    n = len(pages.urls)
    if n == 0:
        return range(0)
    dated = lambda i: pages.get(i)[1] is not None  # noqa: E731
    # empty pages form a block at either end; find the dated span by bisection
    mid = next((i for i in (n // 2, n // 4, 3 * n // 4, 0, n - 1) if dated(i)), None)
    if mid is None:
        return range(n)
    lo, hi = 0, mid  # first dated index in [0, mid]
    while lo < hi:
        m = (lo + hi) // 2
        lo, hi = (lo, m) if dated(m) else (m + 1, hi)
    lo_i = lo
    lo, hi = mid, n - 1  # last dated index in [mid, n-1]
    while lo < hi:
        m = (lo + hi + 1) // 2
        lo, hi = (m, hi) if dated(m) else (lo, m - 1)
    hi_i = lo
    if lo_i >= hi_i:
        return range(lo_i, hi_i + 1)
    inner = _Slice(pages, lo_i, hi_i + 1)
    r = _dated_range(inner, start, end)
    return range(lo_i + r.start, lo_i + r.stop)


class _Slice:
    def __init__(self, pages, a: int, b: int) -> None:
        self.pages, self.a, self.urls = pages, a, pages.urls[a:b]

    def get(self, i: int):
        return self.pages.get(self.a + i)


def _dated_range(pages, start: date, end: date) -> range:
    n = len(pages.urls)
    first, last = pages.get(0)[1], pages.get(n - 1)[1]
    ascending = first <= last

    def before_start(i: int) -> bool:  # page lies entirely before the window start
        d = pages.get(i)[1]
        return d is not None and d < start

    def after_end(i: int) -> bool:
        d = pages.get(i)[1]
        return d is not None and d > end

    # find the boundary indices by bisection, assuming monotone page order
    def bisect(pred_true_first: bool, pred) -> int:
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if pred(mid) == pred_true_first:
                lo = mid + 1
            else:
                hi = mid
        return lo

    if ascending:
        lo = bisect(True, before_start)          # first page not before start
        hi = bisect(False, after_end)            # first page after end
    else:
        lo = bisect(True, after_end)             # first page not after end
        hi = bisect(False, before_start)         # first page before start
    return range(max(0, lo - 1), min(n, hi + 1))


def discover_route(lay: Layout, client: PoliteClient, route: Route, registry: Registry,
                   start: date, end: date) -> dict[str, int]:
    counts = {"children": 0, "urls": 0, "rows": 0}
    _, body = client.get(route.source, use_cache=False)
    children = [e["loc"] for e in parse_sitemap(body)[1]]
    pattern = re.compile(route.include) if route.include else None
    children = [c for c in children if pattern is None or pattern.search(c)]
    if not children:
        return {**counts, "no_children": 1}

    monthly = [(c, child_month(c)) for c in children]
    selected: list[tuple[str, list[dict], date | None]] = []
    if monthly and all(m is not None for _, m in monthly):
        today = datetime.now(UTC).date().replace(day=1)
        for url, month in monthly:
            if _month_overlaps(month, start, end):
                status, body = client.get(url, use_cache=month < today)
                entries = parse_sitemap(body)[1] if status == 200 else []
                selected.append((url, entries, month))
    else:
        pages = _Pages(client, children)
        for i in _paginated_range(pages, start, end):
            entries, median = pages.get(i)
            selected.append((pages.urls[i], entries, median))

    for url, entries, day in selected:
        counts["children"] += 1
        rows = []
        for e in entries:
            counts["urls"] += 1
            canon = canonical_url(e["loc"])
            host = host_of(canon)
            outlet = registry.outlet_for(host)
            if outlet is None or outlet.outlet_id != route.outlet_id:
                continue
            item_day = e["pub_date"].date() if e["pub_date"] else day
            rows.append({"route": "sitemap", "outlet_id": route.outlet_id, "url": canon,
                         "host": host, "day": item_day, "pub_date": e["pub_date"],
                         "lastmod": e["lastmod"], "title": e["title"], "source": url})
        counts["rows"] += len(rows)
        name = hashlib.sha256(url.encode()).hexdigest()[:16]
        write_rows(lay, f"sitemap-{route.outlet_id}", name, rows)
    return counts


def discover(lay: Layout, routes: list[Route], registry: Registry, start: date,
             end: date) -> dict[str, dict[str, int]]:
    client = PoliteClient(lay, index_name="sitemaps")
    out: dict[str, dict[str, int]] = {}
    try:
        for route in routes:
            if route.route != "sitemap" or registry.outlet_for(
                    host_of(route.source)) is None:
                continue
            try:
                out[route.outlet_id] = discover_route(lay, client, route, registry, start, end)
            except Blocked as exc:
                out[route.outlet_id] = {"blocked": 1, "url": str(exc)}  # type: ignore[dict-item]
    finally:
        client.close()
    return out
