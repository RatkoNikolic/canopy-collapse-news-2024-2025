"""Non-news sections, excluded by URL path (PROTOCOL.md §3.2): before fetching, and
again at the scope stages for sections listed after their pages were fetched. registries/nonnews.csv lists, per outlet, a first path segment (or a
whole host, with segment `*`) and the reason. RTS-style script prefixes
(`/lat/`, `/ci/`, `/sr/`) are skipped before the segment is read.
"""

from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlsplit

from canopy_news.config import repo_root

SCRIPT_PREFIXES = {"lat", "ci", "sr", "scc"}


class NonNews:
    def __init__(self, rules: list[dict]) -> None:
        self.by_segment = {(r["outlet_id"], r["segment"]): r["reason"]
                           for r in rules if r["segment"] != "*"}
        self.by_host = {r["host"]: r["reason"] for r in rules if r["segment"] == "*"}

    @classmethod
    def load(cls, path: Path | None = None) -> NonNews:
        path = path or repo_root() / "registries" / "nonnews.csv"
        with Path(path).open(encoding="utf-8", newline="") as fh:
            rows = [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]
        return cls([r for r in rows if r.get("outlet_id")])

    def reason(self, outlet_id: str, url: str) -> str | None:
        """The exclusion reason, or None when the URL is news."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().removeprefix("www.")
        if host in self.by_host:
            return self.by_host[host]
        segments = [s for s in parts.path.split("/") if s]
        while segments and segments[0].lower() in SCRIPT_PREFIXES:
            segments = segments[1:]
        first = segments[0].lower() if segments else ""
        return self.by_segment.get((outlet_id, first))
