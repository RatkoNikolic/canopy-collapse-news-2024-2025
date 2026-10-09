import json

import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import Layout

from canopy_news import hydrate
from canopy_news.documents import extract

PAGE = ("<html><head><title>Naslov</title></head><body><article><h1>Naslov</h1>"
        "<p>Prvi pasus teksta o događaju, dovoljno dug da ga ekstraktor zadrži kao telo.</p>"
        "<p>Drugi pasus sa još nekoliko rečenica koje opisuju šta se dogodilo i zašto.</p>"
        "</article></body></html>").encode()


class _Client:
    pages = {"https://a.rs/1": (200, PAGE), "https://a.rs/2": (200, PAGE.replace(b"Drugi", b"Treci")),
             "https://b.rs/3": (404, b"")}

    def __init__(self, lay, index_name):
        self.calls = 0

    def get(self, url):
        return self.pages[url]

    def close(self):
        pass


def test_hydrate_matches_changes_gone_resumes_and_filters(tmp_path, monkeypatch):
    h = extract(PAGE, "https://a.rs/1", {})["body_hash"]
    rows = [{"event_id": f"e{k}", "url": u, "outlet_id": o, "status": "article", "body_sha256": h}
            for k, (u, o) in enumerate([("https://a.rs/1", "a"), ("https://a.rs/2", "a"),
                                        ("https://b.rs/3", "b")], 1)]
    rows.append({"event_id": "e4", "url": "https://a.rs/4", "outlet_id": "a", "status": "gone",
                 "body_sha256": None})
    pq.write_table(pa.Table.from_pylist(rows), tmp_path / "index.parquet")
    pq.write_table(pa.Table.from_pylist([{"event_id": "e1", "in_scope": True},
                                         {"event_id": "e2", "in_scope": False},
                                         {"event_id": "e3", "in_scope": False}]),
                   tmp_path / "scope.parquet")
    monkeypatch.setattr(hydrate, "PoliteClient", _Client)
    lay, out = Layout(tmp_path), tmp_path / "texts"
    only = hydrate.run(lay, tmp_path / "index.parquet", out=out, scope=tmp_path / "scope.parquet",
                       in_scope_only=True)
    assert only["this_run"] == {"matched": 1}
    res = hydrate.run(lay, tmp_path / "index.parquet", out=out)       # resumes: e1 not redone
    assert res["already_done"] == 1 and res["this_run"] == {"changed": 1, "gone": 1}
    lines = [json.loads(x) for f in out.glob("*.jsonl") for x in f.read_text().splitlines()]
    assert {x["event_id"]: x["outcome"] for x in lines} == {"e1": "matched", "e2": "changed",
                                                            "e3": "gone"}
    assert next(x for x in lines if x["event_id"] == "e1")["body"].startswith("Prvi pasus")
