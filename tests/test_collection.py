import gzip
from datetime import UTC, date, datetime

from chrono_harness import Layout

from canopy_news import mediacloud
from canopy_news.config import WINDOWS, Window
from canopy_news.fetch import candidates
from canopy_news.registry import Outlet, Registry

DUMP = """<?xml version='1.0' encoding='UTF-8'?>
<rss version="2.0"><channel><title>t</title>
<item><link>https://www.blic.rs/vesti/a?utm_source=x&amp;id=1#top</link><pubDate>Sat, 02 Nov 2024 10:00:00 -0000</pubDate><domain>blic.rs</domain><title>A</title><source url="https://www.blic.rs/rss" mcFeedId="1" mcSourceId="2"/></item>
<item><link>http://91.222.7.144/x.html</link><pubDate></pubDate><domain>91.222.7.144</domain><title>B</title><source url="http://www.nspm.rs/rss" mcFeedId="3" mcSourceId="4"/></item>
<item><link>https://www.b92.net/info/vesti/c</link><pubDate>Sat, 02 Nov 2024 11:00:00 -0000</pubDate><domain>b92.net</domain><title>C</title><source url="https://b92.net/rss" mcFeedId="5" mcSourceId="6"/></item>
<item><link>https://example.com/d</link><pubDate>Sat, 02 Nov 2024 11:00:00 -0000</pubDate><domain>example.com</domain><title>D</title><source url="https://example.com/rss" mcFeedId="7" mcSourceId="8"/></item>
</channel></rss>"""


def registry() -> Registry:
    return Registry([
        Outlet("blic", "Blic", ("blic.rs",), "test", "r0"),
        Outlet("b92", "B92", ("b92.net",), "test", "r0"),
    ])


def test_parse_and_candidates():
    items = list(mediacloud.iter_items(gzip.compress(DUMP.encode())))
    assert len(items) == 4
    assert items[0]["pub_date"] == datetime(2024, 11, 2, 10, tzinfo=UTC)
    assert items[1]["pub_date"] is None
    reg = registry()
    picked = [i["title"] for i in items if mediacloud.is_candidate(i, reg.domains)]
    assert picked == ["A", "B", "C"]  # .rs via source feed for B; .net via registry for C
    assert mediacloud.canonical_url(items[0]["link"]) == "https://www.blic.rs/vesti/a?id=1"


def test_registry_matching():
    reg = registry()
    assert reg.outlet_for("www.blic.rs").outlet_id == "blic"
    assert reg.outlet_for("sport.blic.rs").outlet_id == "blic"
    assert reg.outlet_for("notblic.rs") is None


def test_registry_longest_match_and_exclusions():
    reg = Registry([
        Outlet("nova", "Nova", ("nova.rs",), "test", "r0"),
        Outlet("radar", "Radar", ("radar.nova.rs",), "test", "r0"),
        Outlet("politika", "Politika", ("politika.rs",), "test", "r0",
               exclude_hosts=("zurnal.politika.rs",)),
    ])
    assert reg.outlet_for("radar.nova.rs").outlet_id == "radar"
    assert reg.outlet_for("www.nova.rs").outlet_id == "nova"
    assert reg.outlet_for("www.politika.rs").outlet_id == "politika"
    assert reg.outlet_for("zurnal.politika.rs") is None


def test_discover_and_window_selection(tmp_path):
    lay = Layout(tmp_path).ensure()
    from chrono_harness import RawStore

    sha = RawStore(lay.raw).put(gzip.compress(DUMP.encode()), compress=False)
    mediacloud._append_index(lay, {"day": "2024-11-02", "sha256": sha, "status": 200})
    counts = mediacloud.discover(lay, date(2024, 11, 2), date(2024, 11, 2), registry().domains)
    assert counts == {"days": 1, "items": 4, "candidates": 3, "no_dump": 0}
    picked = candidates(lay, WINDOWS["story-v01"], registry(), skip=set())
    assert sorted(c.outlet_id for c in picked) == ["b92", "blic"]  # nspm not in registry
    assert {c.pub_date_source for c in picked} == {"rss"}
    later = Window("later", date(2026, 1, 1), date(2026, 1, 31), "outside the dump's days", False)
    assert candidates(lay, later, registry(), skip=set()) == []


def test_only_the_dataset_window():
    assert list(WINDOWS) == ["story-v01"] and WINDOWS["story-v01"].evaluate is True


def test_registry_collect_only():
    from canopy_news.config import repo_root

    full = Registry.load(repo_root() / "registries" / "outlets.csv")
    collected = Registry.load(repo_root() / "registries" / "outlets.csv", collect_only=True)
    assert len(full.outlets) == 19
    assert sorted(o.outlet_id for o in collected.outlets) == sorted(
        ["n1", "blic", "telegraf", "danas", "nova", "rts", "b92", "informer", "pink"])
    assert collected.outlet_for("politika.rs") is None  # recorded, never fetched


def test_malformed_item_is_recovered_not_fatal():
    bad = DUMP.replace("<title>C</title>", "<title>C \x01 & broken <b></title>")
    items = list(mediacloud.iter_items(gzip.compress(bad.encode())))
    assert len(items) == 4
    assert items[2]["link"] == "https://www.b92.net/info/vesti/c"


def test_page_published_rts_story_date():
    from datetime import UTC, datetime

    from canopy_news.pagedate import page_published
    page = ('<p class="storyDate">\n  четвртак, 14.11.2024,&nbsp;\n   05:55&nbsp;->&nbsp;06:01\n</p>'
            '<p class="storySource"><span>Извор: РТС</span></p>')
    assert page_published(page) == datetime(2024, 11, 14, 4, 55, tzinfo=UTC)   # CET = UTC+1
    summer = '<p class="storyDate">subota, 05.04.2025, 21:10</p>'
    assert page_published(summer) == datetime(2025, 4, 5, 19, 10, tzinfo=UTC)  # CEST = UTC+2
    assert page_published("<p>nothing</p>") is None
