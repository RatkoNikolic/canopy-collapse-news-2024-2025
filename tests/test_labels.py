import json

from chrono_harness import Layout

from canopy_news.labels import _write_jsonl, allocate, draw, import_labels, set_dir, validate


def test_allocate_floor_proportional_and_capped():
    a = allocate({"big": 1000, "mid": 100, "tiny": 2}, 50)
    assert sum(a.values()) == 50
    assert a["tiny"] == 2 and a["big"] > a["mid"] >= 3
    assert allocate({"x": 4, "y": 5}, 50) == {"x": 4, "y": 5}


def _stratum(k):
    return "candidate" if k < 40 else "band-top10" if k < 60 else "rest"


def _pop():
    return ([{"event_id": f"a{k}", "outlet_id": "a", "stratum": _stratum(k)} for k in range(400)] +
            [{"event_id": f"b{k}", "outlet_id": "b", "stratum": _stratum(k * 4)}
             for k in range(100)])


QUOTA = {"candidate": 20, "band-top10": 6, "rest": 10}


def test_draw_strata_weights_exclusion_and_determinism():
    rows = draw(_pop(), QUOTA, seed=1, exclude={"a0"})
    assert draw(_pop(), QUOTA, seed=1, exclude={"a0"}) == rows
    assert len(rows) == 36 and len({r["event_id"] for r in rows}) == 36
    assert "a0" not in {r["event_id"] for r in rows}
    assert sorted(r["position"] for r in rows) == list(range(36))
    w = {r["stratum"]: r["weight"] for r in rows}
    n = {s: sum(r["stratum"] == s for r in rows) for s in w}
    assert w["candidate:a"] * n["candidate:a"] == 39   # N_h / n_h with a0 excluded
    assert round(w["band-top10:b"] * n["band-top10:b"]) == 5   # b15..b19
    assert round(w["rest:b"] * n["rest:b"]) == 85


def _label(eid, **kw):
    return {"event_id": eid, "in_scope": True, "clauses": [2], "evidence": "p1",
            "confidence": "high", "coder": "rn", "labelled_at": "2026-10-03T10:00:00+00:00", **kw}


def test_validate():
    ids = {"e1"}
    assert validate(_label("e1"), ids) is None
    assert validate(_label("e2"), ids) == "event_id not in sample"
    assert validate(_label("e1", clauses=[]), ids)
    assert validate(_label("e1", in_scope=False), ids)
    assert validate(_label("e1", in_scope=False, clauses=[], evidence=None), ids) is None
    assert validate(_label("e1", evidence=None), ids)
    assert validate(_label("e1", confidence="sure"), ids)


def test_import_latest_wins(tmp_path):
    lay = Layout(tmp_path).ensure()
    _write_jsonl(set_dir(lay, "s") / "sample.jsonl", [{"event_id": "e1"}, {"event_id": "e2"}])
    exp = tmp_path / "export.jsonl"
    exp.write_text("\n".join(json.dumps(x) for x in [
        _label("e1"), _label("e1", clauses=[3, 2], labelled_at="2026-10-03T11:00:00+00:00"),
        _label("zz")]) + "\n")
    out = import_labels(lay, "s", exp)
    assert out["labels"] == 1 and out["remaining"] == 1 and len(out["errors"]) == 1
    saved = [json.loads(x) for x in (set_dir(lay, "s") / "labels.jsonl").read_text().splitlines()]
    assert saved[0]["clauses"] == [2, 3]


def _sample300():
    strata = ["candidate"] * 200 + ["band-top10"] * 40 + ["band-next20"] * 30 + ["rest"] * 30
    outlets = ["a", "b", "c"]
    return [{"event_id": f"e{k:03d}", "stratum": f"{s}:{outlets[k % 3]}"}
            for k, s in enumerate(strata)]


def test_assign_shared_overlap_and_even_balanced_split():
    from collections import Counter

    from canopy_news.labels import assign
    rows = assign(_sample300(), ["R1", "R2", "R3"], shared=50, seed=1)
    assert assign(_sample300(), ["R1", "R2", "R3"], shared=50, seed=1) == rows
    assert len(rows) == 300 and len({r["event_id"] for r in rows}) == 300
    shared = [r for r in rows if r["shared"]]
    assert len(shared) == 50 and all(r["coders"] == ["R1", "R2", "R3"] for r in shared)
    per = Counter(c for r in rows for c in r["coders"])
    assert sorted(per.values()) == [133, 133, 134]                     # 50 + 250 / 3
    top = {r["event_id"]: r["stratum"].split(":")[0] for r in _sample300()}
    mix = Counter(top[r["event_id"]] for r in shared)
    assert 33 <= mix["candidate"] <= 34 and 4 <= mix["rest"] <= 6     # shared = the sample's mix
    own = {c: Counter(top[r["event_id"]] for r in rows if r["coders"] == [c])
           for c in ("R1", "R2", "R3")}
    for st in ("candidate", "band-top10", "band-next20", "rest"):     # even within one article
        n = [own[c][st] for c in own]
        assert max(n) - min(n) <= 1


def test_import_refuses_unassigned_coder(tmp_path):
    lay = Layout(tmp_path)
    _write_jsonl(set_dir(lay, "s") / "sample.jsonl", [{"event_id": "e1"}, {"event_id": "e2"}])
    _write_jsonl(set_dir(lay, "s") / "assignment.jsonl",
                 [{"event_id": "e1", "coders": ["R1", "R2"], "shared": True},
                  {"event_id": "e2", "coders": ["R2"], "shared": False}])
    export = tmp_path / "x.jsonl"
    export.write_text(json.dumps(_label("e2", coder="R1")) + "\n" +
                      json.dumps(_label("e1", coder="R1")) + "\n")
    out = import_labels(lay, "s", export)
    assert out["errors"][0]["error"] == "event_id not assigned to this coder"
    assert out["per_coder"]["R1"] == {"labelled": 1, "assigned": 1}


def test_beacon_rounds_and_seeds(tmp_path):
    from datetime import UTC, datetime

    import pytest

    from canopy_news import labels
    t = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    r = labels.round_at(t)
    assert labels.round_time(r) <= t < labels.round_time(r + 1)
    a, b = labels.seeds("ab" * 32)
    assert a != b and labels.seeds("ab" * 32) == (a, b) and labels.seeds("cd" * 32)[0] != a
    with pytest.raises(SystemExit, match="not yet"):                  # a future round is refused
        labels.draw_set(Layout(tmp_path), "s", labels.round_at(datetime(2099, 1, 1, tzinfo=UTC)))
