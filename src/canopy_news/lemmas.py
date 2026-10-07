"""Lemmatisation stage (M2): CLASSLA-Stanza over each document's title, lead
and body (Latin text).

Per document: lowercased lemma strings for title, lead and body (the stage-1
lexicon matches on these), and sentence spans into the body (located by
searching each sentence's text in order, since CLASSLA's own character
offsets restart at every line). Output: builds/lemmas/<LEMMA_VERSION>/
part-*.parquet, keyed by event_id; incremental; one CLASSLA pipeline per
worker process.
"""

from __future__ import annotations

import uuid
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import Layout

from canopy_news.documents import EXTRACTOR_VERSION, doc_dir

LEMMA_VERSION = f"lemma-v2-classla-sr-{EXTRACTOR_VERSION}"

SCHEMA = pa.schema([
    ("event_id", pa.string()), ("outlet_id", pa.string()),
    ("lemmas_title", pa.string()), ("lemmas_lead", pa.string()), ("lemmas_body", pa.string()),
    ("sentence_offsets", pa.list_(pa.list_(pa.int32()))), ("n_tokens", pa.int32()),
])

_NLP = None


def _init() -> None:
    global _NLP
    warnings.filterwarnings("ignore")
    import torch

    torch.set_num_threads(1)  # one thread per worker process: no oversubscription
    import classla

    _NLP = classla.Pipeline("sr", processors="tokenize,pos,lemma", logging_level="ERROR")


def _work(row: dict) -> dict:
    """One CLASSLA call per document over "title \n\n lead \n\n body"; each
    sentence is located in that text and assigned to its part."""
    title, lead, body = row["title"] or "", row["lead"] or "", row["body"] or ""
    text = "\n\n".join([title, lead, body])
    b0 = len(title) + len(lead) + 4  # where the body starts in `text`
    parts = {"title": [], "lead": [], "body": []}
    spans, pos, n = [], 0, 0
    if text.strip():
        for sent in _NLP(text).sentences:
            start = text.find(sent.tokens[0].text, pos)
            last = sent.tokens[-1].text
            end = text.find(last, max(start, pos)) + len(last) if start >= 0 else -1
            part = "body" if start >= b0 else ("lead" if start > len(title) else "title")
            parts[part].extend((w.lemma or w.text).lower() for w in sent.words)
            n += len(sent.words)
            if start >= 0 and end > start:
                pos = end
                if part == "body":
                    spans.append([start - b0, end - b0])
    return {"event_id": row["event_id"], "outlet_id": row["outlet_id"],
            "lemmas_title": " ".join(parts["title"]), "lemmas_lead": " ".join(parts["lead"]),
            "lemmas_body": " ".join(parts["body"]), "sentence_offsets": spans, "n_tokens": n}


def lemma_dir(lay: Layout) -> Path:
    return lay.build_dir("lemmas") / LEMMA_VERSION


def _listing(files: list[Path]) -> str:
    return ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)


def build(lay: Layout, *, workers: int = 8, chunk: int = 2000,
          limit: int | None = None) -> dict[str, int]:
    out_dir = lemma_dir(lay)
    out_dir.mkdir(parents=True, exist_ok=True)
    docs = sorted(doc_dir(lay).glob("part-*.parquet"))
    if not docs:
        return {"processed": 0}
    done_files = sorted(out_dir.glob("part-*.parquet"))
    skip = ""
    if done_files:
        skip = f"WHERE event_id NOT IN (SELECT event_id FROM read_parquet([{_listing(done_files)}]))"
    rows = duckdb.sql(f"""SELECT event_id, outlet_id, title, lead, body
        FROM read_parquet([{_listing(docs)}]) {skip}""").to_arrow_table().to_pylist()
    if limit is not None:
        rows = rows[:limit]
    processed = 0
    with ProcessPoolExecutor(max_workers=workers, initializer=_init) as pool:
        for i in range(0, len(rows), chunk):
            out = list(pool.map(_work, rows[i:i + chunk], chunksize=20))
            pq.write_table(pa.Table.from_pylist(out, schema=SCHEMA),
                           out_dir / f"part-{uuid.uuid4().hex[:12]}.parquet", compression="zstd")
            processed += len(out)
    return {"processed": processed}
