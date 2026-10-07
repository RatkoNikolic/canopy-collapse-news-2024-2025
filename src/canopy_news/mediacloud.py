"""Discovery from Media Cloud's daily URL dumps.

Each day's dump (`mc-YYYY-MM-DD.rss.gz`, ~30–70 MB) lists every story URL
Media Cloud saw that day, one <item> per line: link, pubDate (sometimes
empty), domain (sometimes a bare IP), title and the source feed. Past files
are still served but nothing guarantees they stay up, so:

1. `download` stores every dump as served in raw/ (write-once) and indexes
   it in raw/_index/mediacloud.jsonl. This is the irreversible step.
2. `discover` turns a stored dump into builds/discovery/mediacloud/<day>.parquet:
   the Serbian candidates (any .rs host, or a host in the outlet registry).
   Derived and rebuildable, so the candidate rule can change later.
"""

from __future__ import annotations

import gzip
import html
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import Layout, RawStore
from chrono_harness.timeutil import now_utc

from canopy_news.config import USER_AGENT

DUMP_URL = "https://rss-fetcher.tarbell.mediacloud.org/rss/mc-{day}.rss.gz"

TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid")


# -- index of stored dumps -------------------------------------------------

def _index_path(lay: Layout) -> Path:
    return lay.raw / "_index" / "mediacloud.jsonl"


def read_index(lay: Layout) -> dict[str, dict]:
    path = _index_path(lay)
    if not path.exists():
        return {}
    entries = (json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return {e["day"]: e for e in entries}


def _append_index(lay: Layout, entry: dict) -> None:
    path = _index_path(lay)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def days(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def download(lay: Layout, start: date, end: date, *, pause_s: float = 1.0,
             client: httpx.Client | None = None) -> dict[str, int]:
    """Fetch and store every dump in [start, end] not already indexed.
    Idempotent and resumable; a 404 is indexed as missing, not retried."""
    store = RawStore(lay.raw)
    have = read_index(lay)
    counts = {"stored": 0, "skipped": 0, "missing": 0, "failed": 0}
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120,
                                    follow_redirects=True)
    try:
        for day in days(start, end):
            key = day.isoformat()
            if key in have and have[key].get("sha256") or have.get(key, {}).get("status") == 404:
                counts["skipped"] += 1
                continue
            url = DUMP_URL.format(day=key)
            resp = None
            for attempt in range(4):
                try:
                    resp = client.get(url)
                    if resp.status_code < 500:
                        break
                except httpx.TransportError:
                    resp = None
                time.sleep(2 ** attempt * 5)
            if resp is None or resp.status_code >= 500:
                counts["failed"] += 1
                continue
            entry = {"day": key, "url": url, "fetched_at": now_utc().isoformat(),
                     "status": resp.status_code}
            if resp.status_code == 200:
                entry |= {
                    "sha256": store.put(resp.content, compress=False),
                    "bytes": len(resp.content),
                    "etag": resp.headers.get("etag"),
                    "last_modified": resp.headers.get("last-modified"),
                }
                counts["stored"] += 1
            else:
                counts["missing"] += 1
            _append_index(lay, entry)
            time.sleep(pause_s)
    finally:
        if own:
            client.close()
    return counts


# -- parsing ---------------------------------------------------------------

def canonical_url(url: str) -> str:
    """Lower-case scheme and host, drop the fragment and tracking parameters,
    keep everything else (path case matters on some outlets)."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith(TRACKING_PARAMS)]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(query), ""))


def host_of(url: str | None) -> str:
    if not url:
        return ""
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _pubdate(text: str | None) -> datetime | None:
    if not text or not text.strip():
        return None
    try:
        dt = parsedate_to_datetime(text.strip())
    except (TypeError, ValueError):
        return None
    # "-0000" (Media Cloud's usual zone) means UTC with the local offset unknown
    # (RFC 2822 §3.3); Python returns it as a naive datetime.
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _item_from_xml(line: str) -> dict | None:
    try:
        elem = ET.fromstring(line)
    except ET.ParseError:
        return None
    source = elem.find("source")
    return {
        "link": (elem.findtext("link") or "").strip(),
        "pub_date": _pubdate(elem.findtext("pubDate")),
        "domain": (elem.findtext("domain") or "").strip().lower(),
        "title": (elem.findtext("title") or "").strip(),
        "source_url": source.get("url") if source is not None else None,
        "mc_source_id": source.get("mcSourceId") if source is not None else None,
    }


_FIELD = {k: re.compile(rf"<{k}>(.*?)</{k}>", re.S) for k in ("link", "pubDate", "domain", "title")}
_SOURCE = re.compile(r'<source url="([^"]*)"[^>]*mcSourceId="([^"]*)"')


def _item_from_regex(line: str) -> dict | None:
    """Fallback for an item that is not well-formed XML (stray control
    characters or unescaped markup in a title): take the fields by pattern."""
    link = _FIELD["link"].search(line)
    if not link:
        return None
    def get(k):
        m = _FIELD[k].search(line)
        return html.unescape(m.group(1)).strip() if m else ""
    src = _SOURCE.search(line)
    return {"link": html.unescape(link.group(1)).strip(), "pub_date": _pubdate(get("pubDate")),
            "domain": get("domain").lower(), "title": get("title"),
            "source_url": html.unescape(src.group(1)) if src else None,
            "mc_source_id": src.group(2) if src else None}


def iter_items(dump: bytes) -> Iterator[dict]:
    """One <item> per line in Media Cloud dumps: parse each line on its own,
    so a malformed item is recovered by pattern (or skipped), never fatal."""
    with gzip.GzipFile(fileobj=io.BytesIO(dump)) as fh:
        for raw_line in fh:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line.startswith("<item>"):
                continue
            item = _item_from_xml(line) or _item_from_regex(line)
            if item is not None:
                yield item


def is_candidate(item: dict, registry_domains: set[str]) -> bool:
    """Any .rs host (link, declared domain or source feed), or a host in the
    registry (outlets on .com/.net). Broad on purpose: the outlet filter is
    applied at fetch time, and this table can be rebuilt with a new rule."""
    hosts = {host_of(item["link"]), item["domain"], host_of(item["source_url"])}
    hosts.discard("")
    if any(h.endswith(".rs") for h in hosts):
        return True
    return any(h == d or h.endswith("." + d) for h in hosts for d in registry_domains)


DISCOVERY_SCHEMA = pa.schema([
    ("route", pa.string()),
    ("day", pa.date32()),
    ("url", pa.string()),
    ("link", pa.string()),
    ("host", pa.string()),
    ("pub_date", pa.timestamp("us", tz="UTC")),
    ("domain", pa.string()),
    ("title", pa.string()),
    ("source_url", pa.string()),
    ("mc_source_id", pa.string()),
])


def discovery_dir(lay: Layout) -> Path:
    return lay.build_dir("discovery") / "mediacloud"


def discover(lay: Layout, start: date, end: date, registry_domains: set[str]) -> dict[str, int]:
    """Rebuild the discovery table for every stored dump in [start, end]."""
    store = RawStore(lay.raw)
    index = read_index(lay)
    out_dir = discovery_dir(lay)
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {"days": 0, "items": 0, "candidates": 0, "no_dump": 0}
    for day in days(start, end):
        entry = index.get(day.isoformat())
        if not entry or not entry.get("sha256"):
            counts["no_dump"] += 1
            continue
        rows, seen = [], set()
        for item in iter_items(store.get(entry["sha256"])):
            counts["items"] += 1
            if not item["link"] or not is_candidate(item, registry_domains):
                continue
            url = canonical_url(item["link"])
            if url in seen:
                continue
            seen.add(url)
            rows.append({**item, "route": "mediacloud", "day": day, "url": url,
                         "host": host_of(url)})
        pq.write_table(pa.Table.from_pylist(rows, schema=DISCOVERY_SCHEMA),
                       out_dir / f"{day.isoformat()}.parquet", compression="zstd")
        counts["days"] += 1
        counts["candidates"] += len(rows)
    return counts
