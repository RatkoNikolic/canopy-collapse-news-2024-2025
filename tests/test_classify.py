from chrono_harness import Layout

from canopy_news import classify


def _doc():
    body = "Prvi pasus.\n\nDrugi pasus."
    return {"title": "Naslov", "lead": "Lid", "day": "2025-03-15", "body": body,
            "para_offsets": [[0, 11], [13, len(body)]]}


def test_article_text_numbers_paragraphs_without_outlet():
    t = classify.article_text(_doc())
    assert t.splitlines()[:3] == ["Title: Naslov", "Date: 2025-03-15", "Lead: Lid"]
    assert "[p1] Prvi pasus." in t and "[p2] Drugi pasus." in t


def test_request_per_arm():
    sonnet = classify.request(classify.ARMS["sonnet-think-low"], _doc())
    assert sonnet["output_config"] == {"format": {"type": "json_schema", "schema": classify.SCHEMA},
                                       "effort": "low"}
    assert "temperature" not in sonnet and sonnet["thinking"] == {"type": "adaptive"}
    haiku = classify.request(classify.ARMS["haiku"], _doc())
    assert haiku["temperature"] == 0 and "thinking" not in haiku
    assert haiku["system"][0]["text"].endswith(classify.CODEBOOK.read_text(encoding="utf-8"))


class _Usage:
    input_tokens, cache_read_input_tokens, cache_creation_input_tokens, output_tokens = 1000, 2000, 0, 50


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Fake:
    """A stand-in for anthropic.Anthropic().messages.batches; `bad` ids never parse."""

    def __init__(self, bad=()):
        self.bad, self.made, self.messages = set(bad), {}, self
        self.batches = self

    def create(self, requests):
        bid = f"b{len(self.made)}"
        self.made[bid] = [r["custom_id"] for r in requests]
        return type("B", (), {"id": bid})()

    def retrieve(self, bid):
        return type("B", (), {"processing_status": "ended"})()

    def results(self, bid):
        for i in self.made[bid]:
            text = "not json" if i in self.bad else (
                '{"in_scope": true, "clauses": [3, 2], "evidence": "p1", "confidence": "high"}')
            msg = type("M", (), {"model": "claude-sonnet-5-5", "stop_reason": "end_turn",
                                 "usage": _Usage(), "content": [_Text(text)]})()
            res = type("R", (), {"type": "succeeded", "message": msg})()
            yield type("X", (), {"custom_id": i, "result": res})()


def test_batch_run_collects_retries_gives_up_and_respects_budget(tmp_path, monkeypatch):
    import pytest

    lay = Layout(tmp_path)
    docs = [{**_doc(), "event_id": f"e{k}", "stratum": "candidate"} for k in range(5)]
    monkeypatch.setattr(classify, "targets", lambda lay, ids=None: [
        d for d in docs if ids is None or d["event_id"] in ids])
    fake = _Fake(bad={"e4"})
    out = classify.submit(lay, "main", budget=1.0, client=fake)
    assert out["submitted"] == 5
    st = classify.collect(lay, "main", client=fake)
    assert st["decided"] == 4 and st["in_flight"] == 0
    row = next(r for r in classify.results(classify.run_dir(lay, "main")) if r["event_id"] == "e0")
    assert row["clauses"] == [2, 3] and row["cost_usd"] == pytest.approx(
        (1000 * 2 + 2000 * 2 * 0.1 + 50 * 10) / 1e6 / 2)                 # batch = half price
    for _ in range(2):                                                    # e4 retried, then given up
        assert classify.submit(lay, "main", budget=1.0, client=fake)["submitted"] == 1
        classify.collect(lay, "main", client=fake)
    assert classify.submit(lay, "main", budget=1.0, client=fake)["submitted"] == 0
    assert classify.status(lay, "main")["given_up"] == 1
    with pytest.raises(SystemExit, match="exceeds the approved"):         # budget stop
        classify.submit(lay, "other", budget=0.001, client=fake)


def test_collect_is_idempotent(tmp_path, monkeypatch):
    lay = Layout(tmp_path)
    docs = [{**_doc(), "event_id": f"e{k}", "stratum": "candidate"} for k in range(3)]
    monkeypatch.setattr(classify, "targets", lambda lay, ids=None: docs)
    fake = _Fake()
    classify.submit(lay, "main", budget=1.0, client=fake)
    for _ in range(3):
        classify.collect(lay, "main", client=fake)
    assert len(classify.results(classify.run_dir(lay, "main"))) == 3       # no duplicate rows
