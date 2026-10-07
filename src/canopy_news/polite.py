"""A single-host-at-a-time polite HTTP client for discovery.

Obeys robots.txt (including Crawl-delay), keeps at least `min_interval_s`
between requests to the same host, identifies itself with the project's
user agent, and stores every successful response body in raw/ so that
discovery can be rebuilt without asking the site again.
"""

from __future__ import annotations

import json
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from chrono_harness import Layout, RawStore
from chrono_harness.timeutil import now_utc

from canopy_news.config import USER_AGENT


class Blocked(Exception):
    """robots.txt disallows the URL, or the host's robots.txt is unavailable."""


class PoliteClient:
    def __init__(self, lay: Layout, *, index_name: str, min_interval_s: float = 2.0) -> None:
        self.store = RawStore(lay.raw)
        self.index_path: Path = lay.raw / "_index" / f"{index_name}.jsonl"
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.min_interval_s = min_interval_s
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60,
                                   follow_redirects=True)
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self._interval: dict[str, float] = {}
        self._index = self._read_index()

    def _read_index(self) -> dict[str, dict]:
        if not self.index_path.exists():
            return {}
        rows = (json.loads(x) for x in self.index_path.read_text().splitlines() if x.strip())
        return {r["url"]: r for r in rows}

    def _robots_for(self, host: str) -> urllib.robotparser.RobotFileParser | None:
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                resp = self.client.get(f"https://{host}/robots.txt")
            except httpx.HTTPError:
                rp = None
            else:
                if resp.status_code in (401, 403) or resp.status_code >= 500:
                    rp = None
                else:
                    rp.parse(resp.text.splitlines() if resp.status_code < 300 else [])
            self._robots[host] = rp
            delay = rp.crawl_delay(USER_AGENT) if rp is not None else None
            self._interval[host] = max(self.min_interval_s, float(delay or 0))
        return self._robots[host]

    def cached(self, url: str) -> bytes | None:
        entry = self._index.get(url)
        return self.store.get(entry["sha256"]) if entry and entry.get("sha256") else None

    def get(self, url: str, *, use_cache: bool = True) -> tuple[int, bytes]:
        """(status, body). Successful bodies are stored and indexed; a cached
        copy is returned without a request when `use_cache`."""
        if use_cache and (body := self.cached(url)) is not None:
            return 200, body
        host = urlsplit(url).hostname or ""
        rp = self._robots_for(host)
        if rp is None or not rp.can_fetch(USER_AGENT, url):
            raise Blocked(url)
        wait = self._interval[host] - (time.monotonic() - self._last.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()
        resp = None
        for attempt in range(3):
            try:
                resp = self.client.get(url)
                if resp.status_code < 500:
                    break
            except httpx.TransportError:
                resp = None
            time.sleep(5 * (attempt + 1))
        if resp is None:
            return 0, b""
        if resp.status_code == 200:
            sha = self.store.put(resp.content)
            entry = {"url": url, "sha256": sha, "fetched_at": now_utc().isoformat(),
                     "bytes": len(resp.content)}
            with self.index_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
            self._index[url] = entry
        return resp.status_code, resp.content

    def close(self) -> None:
        self.client.close()
