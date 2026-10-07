"""Publication time as the article page declares it.

Order of preference: JSON-LD `datePublished`; `<meta property="article:
published_time">`; `<meta itemprop="datePublished">`; RTS's visible header
`<p class="storyDate">четвртак, 14.11.2024, 05:55 -> 06:01</p>` (published ->
updated, Belgrade local time; RTS pages declare no machine-readable date).
Returns UTC, or None when the page declares nothing parseable (the discovery
date is then used).
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

_PATTERNS = [
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"'),
    re.compile(r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)'),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time'),
    re.compile(r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)'),
]


def _parse(text: str) -> datetime | None:
    text = text.strip().replace("Z", "+00:00")
    if re.fullmatch(r".*[+-]\d{4}", text):  # +0100 -> +01:00
        text = text[:-2] + ":" + text[-2:]
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return None if dt.tzinfo is None else dt.astimezone(UTC)


_STORY_DATE = re.compile(r'<p class="storyDate">(.*?)</p>', re.S)
_DMY_HM = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4}),?\s*(\d{1,2}):(\d{2})")
BELGRADE = ZoneInfo("Europe/Belgrade")


def _story_date(page: str) -> datetime | None:
    """RTS: the first date and time in the storyDate header (the publication time)."""
    m = _STORY_DATE.search(page)
    if not m:
        return None
    text = " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split())
    d = _DMY_HM.search(text)
    if not d:
        return None
    day, month, year, hour, minute = map(int, d.groups())
    try:
        return datetime(year, month, day, hour, minute, tzinfo=BELGRADE).astimezone(UTC)
    except ValueError:
        return None


def page_published(html: bytes | str) -> datetime | None:
    if isinstance(html, bytes):
        html = html[:400_000].decode("utf-8", "replace")
    for pattern in _PATTERNS:
        for match in pattern.finditer(html):
            dt = _parse(match.group(1))
            if dt is not None:
                return dt
    return _story_date(html)
