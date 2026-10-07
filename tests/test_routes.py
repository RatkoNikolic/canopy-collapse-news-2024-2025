from datetime import UTC, date, datetime

from chrono_harness import Layout

from canopy_news import naslovi, sitemaps
from canopy_news.discovery import write_rows
from canopy_news.fetch import candidates
from canopy_news.config import WINDOWS
from canopy_news.pagedate import page_published
from canopy_news.registry import Outlet, Registry

INDEX = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.blic.rs/sitemap-stories-by-month-2025-1.xml.gz</loc></sitemap>
<sitemap><loc>https://www.telegraf.rs/xml/sitemap/2024/m11</loc></sitemap>
<sitemap><loc>https://n1info.rs/sitemap/sitemap_post_100.xml</loc></sitemap>
</sitemapindex>"""

URLSET = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
 xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
<url><loc>https://n1info.rs/vesti/a/</loc><lastmod>2025-01-09T12:28:12+01:00</lastmod></url>
<url><loc>https://n1info.rs/vesti/b/</loc><lastmod>2025-01-08T10:00:00+01:00</lastmod>
<news:news><news:publication_date>2025-01-08T09:00:00+01:00</news:publication_date>
<news:title>B</news:title></news:news></url>
</urlset>"""


def test_parse_sitemap_and_months():
    kind, entries = sitemaps.parse_sitemap(INDEX)
    assert kind == "index" and len(entries) == 3
    months = [sitemaps.child_month(e["loc"]) for e in entries]
    assert months == [date(2025, 1, 1), date(2024, 11, 1), None]
    kind, entries = sitemaps.parse_sitemap(URLSET)
    assert kind == "urlset"
    assert entries[0]["lastmod"] == datetime(2025, 1, 9, 11, 28, 12, tzinfo=UTC)
    assert entries[1]["pub_date"] == datetime(2025, 1, 8, 8, tzinfo=UTC)
    assert entries[1]["title"] == "B"
    assert sitemaps._median_day(entries) == date(2025, 1, 8)


class _FakePages:
    def __init__(self, medians):
        self.urls = [f"p{i}" for i in range(len(medians))]
        self.medians = medians

    def get(self, i):
        return [], self.medians[i]


def test_paginated_range_both_orders():
    asc = [date(2024, 1, 1) + (date(2024, 1, 8) - date(2024, 1, 1)) * k for k in range(100)]
    start, end = date(2024, 6, 1), date(2024, 7, 31)
    r = sitemaps._paginated_range(_FakePages(asc), start, end)
    covered = [asc[i] for i in r]
    assert covered[0] < start and covered[-1] > end  # one page margin each side
    assert all(start <= d <= end for d in covered[1:-1])
    desc = list(reversed(asc))
    r = sitemaps._paginated_range(_FakePages(desc), start, end)
    covered = [desc[i] for i in r]
    assert covered[0] > end and covered[-1] < start
    assert all(start <= d <= end for d in covered[1:-1])


LISTING = """
<a href="https://naslovi.net/2025-01-15/rts/naslov-prvi/38764728">x</a>
<a href="https://naslovi.net/2025-01-15/rts/naslov-drugi/38763727">y</a>
<a href="https://naslovi.net/2025-01-15/rts/naslov-prvi/38764728">x again</a>
<a href='https://naslovi.net/2025-01-15/rts/povezani-naslov/38760001' class='a-thread'>t</a>
<a href="https://naslovi.net/2025-01-15/izvor/rts/2">2</a>
<a href="https://naslovi.net/2025-01-15/izvor/rts/10">10</a>
"""

ITEM = """<div class="src-btn-container">
<a href='https://www.rts.rs/vesti/svet/5627245/sukob.html' rel="nofollow" class="src-btn" data-x="1">"""


def test_naslovi_parsing():
    items, last = naslovi.parse_listing(LISTING, date(2025, 1, 15), "rts")
    assert items == ["https://naslovi.net/2025-01-15/rts/naslov-prvi/38764728",
                     "https://naslovi.net/2025-01-15/rts/naslov-drugi/38763727",
                     "https://naslovi.net/2025-01-15/rts/povezani-naslov/38760001"]
    assert last == 10
    assert naslovi.parse_item(ITEM) == "https://www.rts.rs/vesti/svet/5627245/sukob.html"
    assert naslovi.listing_url(date(2025, 1, 15), "rts", 3) == \
        "https://naslovi.net/2025-01-15/izvor/rts/3"
    assert naslovi.listing_url(date(2025, 1, 15), "rts", 2, "politika") == \
        "https://naslovi.net/2025-01-15/izvor/rts/politika/2"
    sec = LISTING.replace("izvor/rts/2", "izvor/rts/politika/2").replace("izvor/rts/10", "izvor/rts/politika/4")
    assert naslovi.parse_listing(sec, date(2025, 1, 15), "rts", "politika")[1] == 4


def test_page_published():
    jsonld = b'<script type="application/ld+json">{"datePublished":"2025-01-15T10:30:00+01:00"}</script>'
    assert page_published(jsonld) == datetime(2025, 1, 15, 9, 30, tzinfo=UTC)
    meta = '<meta property="article:published_time" content="2025-01-15T10:30:00+0100">'
    assert page_published(meta) == datetime(2025, 1, 15, 9, 30, tzinfo=UTC)
    assert page_published("<html>no date</html>") is None


def test_candidates_union_routes(tmp_path):
    lay = Layout(tmp_path).ensure()
    reg = Registry([Outlet("rts", "RTS", ("rts.rs",), "t", "r1"),
                    Outlet("n1", "N1", ("n1info.rs",), "t", "r1")])
    write_rows(lay, "naslovi-rts", "2025-01-15", [{
        "route": "naslovi", "outlet_id": "rts", "url": "https://www.rts.rs/a.html",
        "host": "rts.rs", "day": date(2025, 1, 15), "pub_date": None, "lastmod": None,
        "title": None, "source": "x"}])
    write_rows(lay, "sitemap-n1", "p100", [{
        "route": "sitemap", "outlet_id": "n1", "url": "https://n1info.rs/vesti/b/",
        "host": "n1info.rs", "day": date(2025, 1, 8),
        "pub_date": datetime(2025, 1, 8, 8, tzinfo=UTC), "lastmod": None,
        "title": "B", "source": "y"}])
    picked = {c.outlet_id: c for c in candidates(lay, WINDOWS["story-v01"], reg, skip=set())}
    assert set(picked) == {"rts", "n1"}
    assert picked["rts"].pub_date_source == "discovery_day"
    assert picked["n1"].pub_date_source == "rss" and picked["n1"].routes == "sitemap"


def test_paginated_range_skips_empty_edge_pages():
    asc = [date(2024, 1, 1) + (date(2024, 1, 8) - date(2024, 1, 1)) * k for k in range(100)]
    with_empty = asc + [None, None]  # trailing empty pages, as on danas.rs
    start, end = date(2024, 6, 1), date(2024, 7, 31)
    r = sitemaps._paginated_range(_FakePages(with_empty), start, end)
    assert len(r) < 15
    covered = [with_empty[i] for i in r]
    assert covered[0] < start and covered[-1] > end


def test_paginated_range_long_empty_tail():
    asc = [date(2024, 1, 1) + (date(2024, 1, 8) - date(2024, 1, 1)) * k for k in range(100)]
    pages = _FakePages([None] * 3 + asc + [None] * 40)
    r = sitemaps._paginated_range(pages, date(2024, 6, 1), date(2024, 7, 31))
    assert len(r) < 15 and all(pages.medians[i] is not None for i in r)



def test_nonnews_rules():
    from canopy_news.nonnews import NonNews

    nn = NonNews.load()
    assert nn.reason("telegraf", "https://www.telegraf.rs/sport/fudbal/123") == "sport"
    assert nn.reason("telegraf", "https://www.telegraf.rs/vesti/politika/123") is None
    assert nn.reason("telegraf", "https://ljubimci.telegraf.rs/vesti-i-dogadjaji/1") == "pets"
    assert nn.reason("rts", "https://www.rts.rs/lat/sport/fudbal/5627245/x.html") == "sport"
    assert nn.reason("rts", "https://www.rts.rs/vesti/drustvo/5627245/x.html") is None
    assert nn.reason("danas", "https://www.danas.rs/bbc-news-serbian/x/").startswith("BBC")
    assert nn.reason("n1", "https://n1info.rs/vesti/x/") is None



def test_retry_after_parsing_and_plantbased_excluded():
    from canopy_news.fetch import _retry_after
    from canopy_news.nonnews import NonNews

    assert _retry_after("120") == 120.0 and _retry_after(None) == 60.0
    assert _retry_after("1") == 5.0 and _retry_after("junk") == 60.0
    assert NonNews.load().reason("telegraf", "https://plantbased.telegraf.rs/pb-vesti/x/1").startswith("lifestyle")



def test_lexicon_terms():
    from canopy_news import lexicon

    terms = lexicon.load()
    hit = lexicon.match("pad nadstrešnice na železničkoj stanici u novom sadu", terms)
    assert "collapse" in hit
    assert not lexicon.match("nadstrešnica iznad ulaza u tržni centar", terms).get("collapse")
    both = lexicon.match("blokaderi su ponovo izašli, a zbor građana je odlučio", terms)
    assert set(both) == {"government", "protester"}
    assert lexicon.match("studenti u blokadi", terms).get("neutral")
