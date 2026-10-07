"""Relevance stage 2: the embedding band (PROTOCOL.md §5.3, §6).

Every article is scored by cosine similarity to the story centroid. Before the
human labels exist the centroid is a proxy: the lexicon candidates. It is
**outlet-balanced** — the mean of each outlet's own candidate centroid — because
candidate rates differ by outlet (6% to 39%) and a pooled mean would lean towards
how the outlets with most candidates write about the story; each outlet weighs the
same. After labelling, the centroid is recomputed from the in-scope gold articles
and the band's cut-off is fixed on the gold sample (§4.3); until then this module
provides the ranking and the strata the gold sample and the recall estimate use
(§5): non-candidates in the top decile of similarity, the next two deciles, and the
rest.

Output: builds/scope/band-<lexicon version>-<embedding version>.parquet
(event_id, outlet_id, candidate, score, stratum) and a report.
"""

from __future__ import annotations

import json
from collections import defaultdict

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import Layout

from canopy_news import embeddings, lexicon
from canopy_news.documents import doc_dir

STRATA = (("band-top10", 0.90), ("band-next20", 0.70), ("rest", 0.0))  # non-candidate percentiles


def _listing(files) -> str:
    return ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)


def balanced_centroid(vectors: np.ndarray, outlets: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Unit-length mean of the per-outlet means of the masked vectors."""
    means = [vectors[mask & (outlets == o)].mean(axis=0)
             for o in np.unique(outlets[mask])]
    c = np.mean(means, axis=0)
    return c / np.linalg.norm(c)


def stratum(score: float, cuts: dict[str, float]) -> str:
    if score >= cuts["band-top10"]:
        return "band-top10"
    if score >= cuts["band-next20"]:
        return "band-next20"
    return "rest"


def build(lay: Layout) -> dict:
    lex_ver = lexicon.version(lexicon.load())
    lex = lay.build_dir("scope") / f"{lex_ver}.parquet"
    if not lex.exists():
        raise SystemExit(f"{lex.name} missing: run `canopy-news lexicon` first")
    vec_parts = sorted(embeddings.emb_dir(lay, "documents").glob("part-*.parquet"))
    docs = sorted(doc_dir(lay).glob("part-*.parquet"))
    tbl = duckdb.sql(f"""SELECT e.event_id, e.outlet_id, l.candidate, e.vector, d.title
        FROM read_parquet([{_listing(vec_parts)}]) e
        JOIN read_parquet('{lex}') l USING (event_id)
        JOIN read_parquet([{_listing(docs)}]) d USING (event_id)
        WHERE d.error IS NULL
        ORDER BY e.event_id""").to_arrow_table()   # fixed order: the centroid's float sum, and
    # with it every score, is identical on rerun
    ids = tbl["event_id"].to_pylist()
    outlets = np.array(tbl["outlet_id"].to_pylist())
    cand = np.array(tbl["candidate"].to_pylist(), dtype=bool)
    flat = tbl["vector"].combine_chunks()
    vectors = flat.values.to_numpy(zero_copy_only=False).reshape(len(flat), -1).astype(np.float32)
    centroid = balanced_centroid(vectors, outlets, cand)
    scores = vectors @ centroid
    other = scores[~cand]
    cuts = {name: float(np.quantile(other, q)) for name, q in STRATA}
    strata = ["candidate" if c else stratum(s, cuts) for c, s in zip(cand, scores, strict=True)]
    out = lay.build_dir("scope") / f"band-{lex_ver}-{embeddings.EMBED_VERSION}.parquet"
    pq.write_table(pa.table({"event_id": ids, "outlet_id": outlets.tolist(),
                             "candidate": cand.tolist(), "score": scores.astype(np.float32),
                             "stratum": strata}), out, compression="zstd")
    by_outlet: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for o, st in zip(outlets, strata, strict=True):
        by_outlet[str(o)][st] += 1
    titles = tbl["title"].to_pylist()
    top_other = [titles[i] for i in np.argsort(-np.where(cand, -1, scores))[:15]]
    report = {
        "file": out.name, "articles": len(ids), "candidates": int(cand.sum()),
        "centroid": "outlet-balanced mean of lexicon-candidate vectors (proxy until gold)",
        "cuts": {k: round(v, 4) for k, v in cuts.items()},
        "score_median": {"candidates": round(float(np.median(scores[cand])), 4),
                         "others": round(float(np.median(other)), 4)},
        "auc_candidates_vs_others": round(float(_auc(scores[cand], other)), 4),
        "by_outlet": {o: dict(v) for o, v in sorted(by_outlet.items())},
        "top_non_candidates": top_other,
    }
    (lay.build_dir("scope") / f"{out.stem}_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """Probability a random candidate outscores a random non-candidate (rank-based)."""
    allv = np.concatenate([pos, neg])
    ranks = allv.argsort().argsort() + 1
    return (ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))
