"""The release files (PROTOCOL.md §7): what the dataset publishes, without article text.

    canopy-news release --version 1.0.0     → release/<version>/

- index.parquet: one row per article URL the fetch reached in the window: outlet, status,
  publication and fetch times (UTC), how the date was obtained, the discovery route, the
  sha256 of the stored page and of the extracted body, body length, extractor version.
- scope.parquet: per article in the corpus: lexicon hits, band score and stratum, and
  (once run) the classifier's decision and clauses.
- coverage.parquet: discovered / fetched / dated_out / gone / failed per outlet × day.
- manifest.json and SHA256SUMS.

Titles, bodies and lemmas are never written: the event log's attrs carry the headline, so
the log itself is not released, only this export of it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, time
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import EventLog, Layout
from chrono_harness.timeutil import now_utc, to_utc

from canopy_news import embeddings, lexicon
from canopy_news.config import CORPUS, WINDOWS, repo_root
from canopy_news.documents import current_inserts, doc_dir, soft_404
from canopy_news.labels import codebook_sha256
from canopy_news.nonnews import NonNews

TEXT_COLUMNS = {"title", "lead", "body", "title_original", "body_original", "text", "lemmas"}


def _listing(files) -> str:
    return ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)


def _attrs(e) -> dict:
    a = e.attrs
    return json.loads(a) if isinstance(a, str) else dict(a or {})


def index_rows(lay: Layout, window: str = "story-v01") -> list[dict]:
    w = WINDOWS[window]
    start = to_utc(w.start)
    end = to_utc(datetime.combine(w.end, time.max).replace(tzinfo=None).isoformat() + "+00:00")
    nonnews = NonNews.load()
    docs = {r["event_id"]: r for r in duckdb.sql(f"""SELECT event_id, body_hash, n_chars,
        extractor, error FROM read_parquet([{_listing(sorted(doc_dir(lay).glob('part-*.parquet')))}])
        """).to_arrow_table().to_pylist()}
    log = EventLog(lay.log)
    inserted = set()
    rows = []
    for e in current_inserts(log):
        a = _attrs(e)
        inserted.add(e.unit_id)
        d = docs.get(e.event_id, {})
        if not start <= e.valid_time <= end:
            status = "dated_out"
        elif soft_404(e.unit_id, a.get("final_url")) or d.get("error") == "soft_404":
            status = "gone"
        elif nonnews.reason(a.get("outlet_id", ""), e.unit_id):
            status = "excluded_section"
        elif d.get("error"):
            status = f"no_text:{d['error']}"
        else:
            status = "article"
        rows.append({"event_id": e.event_id, "url": e.unit_id, "final_url": a.get("final_url"),
                     "outlet_id": a.get("outlet_id"), "status": status,
                     "published_at": e.valid_time.isoformat(),
                     "date_source": a.get("pub_date_source"),
                     "fetched_at": e.ingest_time.isoformat(),
                     "discovered_via": a.get("discovered_via"),
                     "page_sha256": e.content_sha256, "body_sha256": d.get("body_hash"),
                     "body_chars": d.get("n_chars"), "extractor": d.get("extractor")})
    for e in log.as_of(now_utc(), corpus=CORPUS, clock="ingest"):
        if e.kind == "delete" and e.unit_id not in inserted:
            a = _attrs(e)
            inserted.add(e.unit_id)
            rows.append({"event_id": e.event_id, "url": e.unit_id, "final_url": None,
                         "outlet_id": a.get("outlet_id"), "status": "gone",
                         "published_at": e.valid_time.isoformat() if e.valid_time else None,
                         "date_source": a.get("pub_date_source"),
                         "fetched_at": e.ingest_time.isoformat(),
                         "discovered_via": a.get("discovered_via"), "page_sha256": None,
                         "body_sha256": None, "body_chars": None, "extractor": None})
    return sorted(rows, key=lambda r: r["url"])


def scope_rows(lay: Layout, article_ids: set[str]) -> list[dict]:
    lex_ver = lexicon.version(lexicon.load())
    lex = lay.build_dir("scope") / f"{lex_ver}.parquet"
    band = lay.build_dir("scope") / f"band-{lex_ver}-{embeddings.EMBED_VERSION}.parquet"
    hits = ", ".join(f"l.hit_{x}" for x in lexicon.LISTS)
    rows = duckdb.sql(f"""SELECT l.event_id, l.candidate AS lexicon_candidate, {hits},
        b.score AS band_score, b.stratum AS band_stratum
        FROM read_parquet('{lex}') l LEFT JOIN read_parquet('{band}') b USING (event_id)
        ORDER BY l.event_id""").to_arrow_table().to_pylist()
    return [r for r in rows if r["event_id"] in article_ids]


def _write(rows: list[dict], path: Path) -> None:
    table = pa.Table.from_pylist(rows)
    leaked = TEXT_COLUMNS & set(table.column_names)
    if leaked:
        raise SystemExit(f"refusing to release text columns: {sorted(leaked)}")
    pq.write_table(table, path, compression="zstd")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(lay: Layout, version: str) -> dict:
    out = repo_root() / "release" / version
    out.mkdir(parents=True, exist_ok=True)
    index = index_rows(lay)
    _write(index, out / "index.parquet")
    articles = {r["event_id"] for r in index if r["status"] == "article"}
    _write(scope_rows(lay, articles), out / "scope.parquet")
    cov = lay.build_dir("coverage") / "story-v01.parquet"
    if not cov.exists():
        raise SystemExit("coverage missing: run `canopy-news coverage` first")
    pq.write_table(pq.read_table(cov), out / "coverage.parquet", compression="zstd")
    status: dict[str, int] = {}
    for r in index:
        status[r["status"]] = status.get(r["status"], 0) + 1
    git = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo_root(),
                         capture_output=True, text=True)
    commit = git.stdout.strip() if git.returncode == 0 else None
    manifest = {"dataset": "canopy-collapse-news-2024-2025", "version": version,
                "built_at": now_utc().isoformat(), "code_commit": commit,
                "window": {"start": WINDOWS["story-v01"].start.isoformat(),
                           "end": WINDOWS["story-v01"].end.isoformat()},
                "urls": len(index), "status": dict(sorted(status.items())),
                "articles": len(articles), "lexicon": lexicon.version(lexicon.load()),
                "embedding": embeddings.EMBED_VERSION, "codebook_sha256": codebook_sha256()}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    files = sorted(p for p in out.iterdir() if p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text("".join(f"{_sha(p)}  {p.name}\n" for p in files))
    return manifest
