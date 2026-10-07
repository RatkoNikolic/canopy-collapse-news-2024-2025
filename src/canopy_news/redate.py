"""Correct publication times that were recorded from the discovery day.

An article whose page declared no date the fetcher could read got its route's
discovery day as `valid_time` (attrs.pub_date_source != "page"). When the date
reader learns a page's format (RTS's storyDate header, 2026-10-04), the stored
page is read again and, if it now yields a time, a corrected `insert` is
appended: same unit, same raw object, the page's time as `valid_time`, ingest
time now, `attrs.corrects` = the event it corrects. The log stays append-only
and bi-temporal (the replay knows when the time was learned); readers take the
latest-recorded insert per unit (`documents.current_inserts`).

Derived stages follow: documents of corrected or no-longer-in-window events are
dropped and the corrected events extracted again (their `valid_time` changes);
lemma rows and vectors move to the correcting event's id (same page, same text,
nothing recomputed or paid for); rows of events now outside the window go.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb
from chrono_harness import Event, EventLog, Layout, RawStore, Run, RunManifest
from chrono_harness.timeutil import now_utc

from canopy_news import documents, embeddings, lemmas
from canopy_news.config import CORPUS, Window
from canopy_news.pagedate import page_published

NOTE = ("publication time read again from the stored page (date reader learned the page's "
        "format); the corrected event carried the discovery day")


def corrections(lay: Layout, run_id: str) -> list[Event]:
    store = RawStore(lay.raw)
    out = []
    for e in documents.current_inserts(EventLog(lay.log)):
        if e.attrs.get("pub_date_source") == "page" or not e.content_sha256:
            continue
        dt = page_published(store.get(e.content_sha256))
        if dt is None or dt == e.valid_time:
            continue
        out.append(Event.make(
            corpus=e.corpus, kind="insert", unit_id=e.unit_id, valid_time=dt,
            ingest_time=now_utc(), content_sha256=e.content_sha256, pass_id=run_id,
            attrs={**e.attrs, "pub_date_source": "page", "corrects": e.event_id,
                   "correction": NOTE}))
    return out


def reconcile(directory: Path, keep: set[str], remap: dict[str, str]) -> dict[str, int]:
    """Rewrite a stage's parts: ids in `remap` take the new id; rows whose (new) id is
    not in `keep` go. The new part is written before the old ones are removed."""
    files = sorted(directory.glob("part-*.parquet"))
    if not files:
        return {"rows": 0, "remapped": 0, "dropped": 0}
    listing = ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)
    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE remap(old VARCHAR, new VARCHAR)")
    if remap:
        con.executemany("INSERT INTO remap VALUES (?, ?)", list(remap.items()))
    con.execute("CREATE TEMP TABLE keep(id VARCHAR)")
    con.executemany("INSERT INTO keep VALUES (?)", [(k,) for k in keep])
    before = con.execute(f"SELECT count(*) FROM read_parquet([{listing}])").fetchone()[0]
    remapped = con.execute(f"""SELECT count(*) FROM read_parquet([{listing}]) p
        JOIN remap r ON p.event_id = r.old""").fetchone()[0]
    tmp = directory / f"tmp-{uuid.uuid4().hex[:12]}.parquet"
    con.execute(f"""COPY (
        SELECT * REPLACE (coalesce(r.new, p.event_id) AS event_id)
        FROM read_parquet([{listing}]) p LEFT JOIN remap r ON p.event_id = r.old
        WHERE coalesce(r.new, p.event_id) IN (SELECT id FROM keep)
        QUALIFY row_number() OVER (PARTITION BY coalesce(r.new, p.event_id)
                                   ORDER BY (r.new IS NOT NULL) DESC) = 1
    ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)""")
    after = con.execute(f"SELECT count(*) FROM '{tmp}'").fetchone()[0]
    con.close()
    tmp.rename(directory / f"part-{uuid.uuid4().hex[:12]}.parquet")
    for f in files:
        f.unlink()
    return {"rows": after, "remapped": remapped, "dropped": before - after}


def run(lay: Layout, window: Window, *, workers: int = 4) -> dict:
    log = EventLog(lay.log)
    manifest = RunManifest(kind="correction", corpus=CORPUS,
                           params={"window": window.name, "what": "valid_time from page"},
                           data_hashes={"log_before": log.fingerprint()})
    with Run(lay.runs, manifest, label="redate") as run:
        events = corrections(lay, run.run_id)
        if events:
            log.append(events, shard=f"{run.run_id}-redate")
        current = {e.event_id for e in documents.window_inserts(lay, window)}
        remap = {e.attrs["corrects"]: e.event_id for e in events}
        report = {"corrected": len(events),
                  "corrected_now_outside_window": sum(e.event_id not in current for e in events)}
        # documents: corrected events change valid_time, so they are extracted again
        report["documents_pruned"] = reconcile(documents.doc_dir(lay), current, {})
        report["documents_built"] = documents.build(lay, window, workers=workers)
        report["lemmas"] = reconcile(lemmas.lemma_dir(lay), current, remap)
        report["embeddings"] = reconcile(embeddings.emb_dir(lay, "documents"), current, remap)
        run.manifest.params |= {k: v for k, v in report.items() if isinstance(v, int)}
        run.manifest.data_hashes["log_after"] = log.fingerprint()
    return report
