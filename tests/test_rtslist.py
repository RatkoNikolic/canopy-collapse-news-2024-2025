from datetime import date

from canopy_news.rtslist import Section, day_medians, day_of, id_bounds, parse_page

PAGE = """<div class="sidebar"><a href="/vesti/drustvo/6054109/najnovije.html" class="largeThumb">x</a></div>
<div id="storyBrowser"><div class="element first">
<a href="/vesti/politika/5761595/protest-novi-pazar-sud.html" class="largeThumb" title="a">
<a href="/vesti/politika/5761595/protest-novi-pazar-sud.html">again</a>
<a href="/vesti/politika/5761592/kancelarija.html" class="largeThumb" title="b">
<nav aria-label="Pagination"><a href="/vesti/hronika/5000000/x.html" class="largeThumb"></a></nav>"""


def test_parse_page_section_stories_only():
    assert parse_page(PAGE) == [
        ("https://www.rts.rs/vesti/politika/5761595/protest-novi-pazar-sud.html", 5761595),
        ("https://www.rts.rs/vesti/politika/5761592/kancelarija.html", 5761592)]
    assert parse_page("<html>no list</html>") == []


def test_day_of_interpolates_and_extrapolates():
    cal = [(100, date(2024, 11, 1)), (200, date(2024, 11, 11))]          # 10 IDs a day
    assert day_of(cal, 150) == date(2024, 11, 6)
    assert day_of(cal, 80) == date(2024, 10, 30) and day_of(cal, 230) == date(2024, 11, 14)


def test_day_medians_ignore_old_related_stories():
    from datetime import timedelta
    pairs = []
    for k in range(20):                     # day k: stories 1000+10k .. +9, plus one old repost
        d = date(2024, 11, 1) + timedelta(k)
        pairs += [(1000 + 10 * k + j, d) for j in range(10)] + [(5, d)]
    pairs.append((1, date(2024, 11, 20)))   # a very old story listed late must not move day 1
    cal = day_medians(pairs)
    assert cal[0] == (1004, date(2024, 11, 1)) and day_of(cal, 1004) == date(2024, 11, 1)
    lo, hi = id_bounds(cal, date(2024, 11, 1), date(2024, 11, 20))
    assert lo == 1004 - 30 and hi == cal[-1][0] + 30


class FakeSection(Section):
    """Listing of IDs 10_000 down to 1, ten a page, positions from 0; empty past the end."""

    def __init__(self):
        self.memo = {}

    def page(self, position):
        top = 10_000 - 10 * position
        return [(f"u{i}", i) for i in range(top, max(top - 10, 0), -1)]


def test_window_pages_bisect():
    first, last = FakeSection().window_pages(4_005, 6_000)
    s = FakeSection()
    assert max(i for _, i in s.page(first)) >= 6_000 >= min(i for _, i in s.page(first))
    assert min(i for _, i in s.page(last)) <= 4_005 <= max(i for _, i in s.page(last))
    assert first == 400 and last == 599
