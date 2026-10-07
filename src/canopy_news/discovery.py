"""Shared pieces of the discovery routes.

Every route writes Parquet files under builds/discovery/<route-dir>/ with at
least these columns: route, url (canonical), host, day (the date the route
attributes to the item), pub_date (when the route states one), title. The
fetcher reads all route directories together. Discovery is derived state:
it can be rebuilt from raw/ (dumps, stored sitemaps, stored listing pages).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import Layout

from canopy_news.config import repo_root

TS = pa.timestamp("us", tz="UTC")

ROUTE_SCHEMA = pa.schema([
    ("route", pa.string()),
    ("outlet_id", pa.string()),
    ("url", pa.string()),
    ("host", pa.string()),
    ("day", pa.date32()),
    ("pub_date", TS),
    ("lastmod", TS),
    ("title", pa.string()),
    ("source", pa.string()),  # the sitemap or listing page the URL came from
])


def discovery_root(lay: Layout) -> Path:
    return lay.build_dir("discovery")


def discovery_files(lay: Layout) -> list[Path]:
    return sorted(discovery_root(lay).glob("*/*.parquet"))


def write_rows(lay: Layout, subdir: str, name: str, rows: list[dict]) -> Path:
    out = discovery_root(lay) / subdir / f"{name}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=ROUTE_SCHEMA), out, compression="zstd")
    return out


@dataclass(frozen=True)
class Route:
    outlet_id: str
    route: str  # sitemap | naslovi
    source: str  # sitemap index URL, or the naslovi.net source slug
    include: str  # regex a child sitemap URL must match (sitemap route)


def load_routes(path: Path | None = None) -> list[Route]:
    path = path or repo_root() / "registries" / "discovery.csv"
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return [Route(r["outlet_id"].strip(), r["route"].strip(), r["source"].strip(),
                      (r.get("include") or "").strip())
                for r in csv.DictReader(fh) if (r.get("outlet_id") or "").strip()]
