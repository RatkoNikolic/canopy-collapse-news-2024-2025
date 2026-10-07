import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import Layout

from canopy_news import carryover, documents, embeddings, lemmas


def _docs(d, rows):
    d.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), d / "part-a.parquet")


def test_carryover_copies_unchanged_and_drops_changed(tmp_path, monkeypatch):
    lay = Layout(tmp_path).ensure()
    prev = "doc-old"
    base = {"title": "T", "lead": "L", "error": None}
    _docs(lay.build_dir("documents") / prev, [
        {"event_id": "same", **base, "body": "b"}, {"event_id": "edit", **base, "body": "old"},
        {"event_id": "gone", **base, "body": "x"}])
    _docs(documents.doc_dir(lay), [
        {"event_id": "same", **base, "body": "b"}, {"event_id": "edit", **base, "body": "new"},
        {"event_id": "gone", "title": "T", "lead": "", "body": "", "error": "soft_404"}])
    _docs(lay.build_dir("lemmas") / f"lemma-v2-classla-sr-{prev}",
          [{"event_id": e, "lemmas_body": e} for e in ("same", "edit", "gone")])
    _docs(embeddings.emb_dir(lay, "documents"),
          [{"event_id": e, "vector": [1.0]} for e in ("same", "edit", "gone")])
    out = carryover.run(lay, prev)
    assert (out["unchanged"], out["changed"], out["errors"], out["lemmas_copied"]) == (1, 1, 1, 1)
    lem = pq.read_table(next(lemmas.lemma_dir(lay).glob("part-*.parquet"))).to_pylist()
    vec = pq.read_table(next(embeddings.emb_dir(lay, "documents").glob("part-*.parquet"))).to_pylist()
    assert [r["event_id"] for r in lem] == ["same"] and [r["event_id"] for r in vec] == ["same"]
