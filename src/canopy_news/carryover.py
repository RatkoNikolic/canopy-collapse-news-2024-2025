"""Carry derived rows across an extractor bump when an article's text did not change.

A new extractor version rebuilds every document (minutes) and, by its version
string, every lemma row (hours of CPU). Most articles come out identical, so:
lemma rows of articles whose title, lead and body are unchanged are copied from
the previous version's lemma directory; vectors (keyed by event id, not by
extractor version) are kept for those and dropped for the rest, which the
embedding loop then embeds again. Articles that changed, or are now errors
(e.g. soft-404 pages), are left to the normal stages.
"""

from __future__ import annotations

import uuid

import duckdb
from chrono_harness import Layout

from canopy_news import embeddings, lemmas
from canopy_news.documents import doc_dir
from canopy_news.redate import reconcile


def _listing(files) -> str:
    return ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)


def run(lay: Layout, prev_version: str) -> dict:
    prev_docs = sorted((lay.build_dir("documents") / prev_version).glob("part-*.parquet"))
    cur_docs = sorted(doc_dir(lay).glob("part-*.parquet"))
    if not prev_docs or not cur_docs:
        raise SystemExit("both the previous and the current documents must exist")
    sig = "md5(coalesce(title,'') || '\x1f' || coalesce(lead,'') || '\x1f' || coalesce(body,''))"
    con = duckdb.connect()
    con.execute(f"""CREATE TEMP TABLE cmp AS
        SELECT c.event_id, c.error IS NULL AS ok, p.event_id IS NOT NULL AS had,
               {sig.replace('title', 'c.title').replace('lead', 'c.lead').replace('body', 'c.body')}
                 = {sig.replace('title', 'p.title').replace('lead', 'p.lead').replace('body', 'p.body')} AS same
        FROM read_parquet([{_listing(cur_docs)}]) c
        LEFT JOIN read_parquet([{_listing(prev_docs)}]) p USING (event_id)""")
    unchanged = {r[0] for r in con.execute(
        "SELECT event_id FROM cmp WHERE ok AND had AND same").fetchall()}
    stats = dict(zip(("documents", "unchanged", "changed", "errors"), con.execute("""
        SELECT count(*), count(*) FILTER (WHERE ok AND had AND same),
               count(*) FILTER (WHERE ok AND NOT (had AND coalesce(same, false))),
               count(*) FILTER (WHERE NOT ok) FROM cmp""").fetchone(), strict=True))
    # lemmas: copy the previous version's rows for unchanged articles not yet present
    prev_lem = lay.build_dir("lemmas") / f"lemma-v2-classla-sr-{prev_version}"
    cur_lem = lemmas.lemma_dir(lay)
    cur_lem.mkdir(parents=True, exist_ok=True)
    prev_parts = sorted(prev_lem.glob("part-*.parquet"))
    have = sorted(cur_lem.glob("part-*.parquet"))
    con.execute("CREATE TEMP TABLE keep(id VARCHAR)")
    con.executemany("INSERT INTO keep VALUES (?)", [(k,) for k in unchanged])
    copied = 0
    if prev_parts:
        skip = (f"AND event_id NOT IN (SELECT event_id FROM read_parquet([{_listing(have)}]))"
                if have else "")
        out = cur_lem / f"part-{uuid.uuid4().hex[:12]}.parquet"
        con.execute(f"""COPY (SELECT * FROM read_parquet([{_listing(prev_parts)}])
            WHERE event_id IN (SELECT id FROM keep) {skip})
            TO '{out}' (FORMAT parquet, COMPRESSION zstd)""")
        copied = con.execute(f"SELECT count(*) FROM '{out}'").fetchone()[0]
        if not copied:
            out.unlink()
    con.close()
    stats["lemmas_copied"] = copied
    stats["vectors"] = reconcile(embeddings.emb_dir(lay, "documents"), unchanged, {})
    return stats
