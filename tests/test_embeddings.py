import json

import pytest

from canopy_news import embeddings as em
from canopy_news.config import load_env


def test_texts_follow_the_gemini_embedding_2_prefixes():
    assert em.doc_text("Naslov", "Uvod", "Telo") == "title: Naslov | text: Uvod\nTelo"
    assert em.doc_text(None, None, "x" * 9000).endswith("x" * em.BODY_CHARS)
    assert em.doc_text(None, "", "t").startswith("title: none | text: t")
    assert em.query_text("ko?") == "task: search result | query: ko?"


def test_request_line_one_content_and_dims():
    rec = json.loads(em.request_line("e1", "tekst"))
    assert rec["key"] == "e1"
    assert rec["request"]["content"] == {"parts": [{"text": "tekst"}]}
    assert rec["request"]["output_dimensionality"] == em.DIMS


def test_parse_output_line():
    v = [0.1] * em.DIMS
    assert em.parse_output_line(json.dumps({"key": "a", "response": {"embedding": {"values": v}}})) == ("a", v, None)
    assert em.parse_output_line(json.dumps({"key": "b", "response": {"embeddings": [{"values": v}]}}))[1] == v
    key, vec, err = em.parse_output_line(json.dumps({"key": "c", "error": {"code": 400}}))
    assert key == "c" and vec is None and "400" in err
    assert em.parse_output_line(json.dumps({"key": "d", "response": {"embedding": {"values": [0.1] * 3}}}))[1] is None
    assert em.parse_output_line(json.dumps({"key": "e", "response": {"embedding": {"values": [None] * em.DIMS}}}))[1] is None


def test_check_vector_refuses_nan_and_wrong_length():
    with pytest.raises(ValueError):
        em.check_vector([float("nan")] * em.DIMS)
    with pytest.raises(ValueError):
        em.check_vector([0.0] * 10)


def test_budget_counts_all_but_dead_batches():
    batches = [{"state": "JOB_STATE_RUNNING", "est_cost_usd": 5.0},
               {"state": "JOB_STATE_SUCCEEDED", "est_cost_usd": 4.0},
               {"state": "JOB_STATE_FAILED", "est_cost_usd": 9.0}]
    assert em.committed_cost(batches) == 9.0
    tokens, cost = em.estimate_cost(4_000_000, 4.0)
    assert tokens == 1_000_000 and cost == pytest.approx(0.10)


def test_load_env(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# c\nGEMINI_API_KEY='abc'\nEMPTY=\nSET=new\n")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SET", "old")
    load_env(f)
    import os
    assert os.environ["GEMINI_API_KEY"] == "abc" and os.environ["SET"] == "old"
    assert "EMPTY" not in os.environ


def test_token_chunks():
    texts = [(str(i), "x" * 400) for i in range(10)]           # 100 tokens each at 4 chars/token
    chunks = em.token_chunks(texts, 4.0, 300)
    assert [len(c) for c in chunks] == [3, 3, 3, 1]
    assert [k for c in chunks for k, _ in c] == [str(i) for i in range(10)]
    assert em.token_chunks([("big", "x" * 4000)], 4.0, 300) == [[("big", "x" * 4000)]]
    assert em.token_chunks([], 4.0, 300) == []


def test_quota_error():
    class E(Exception):
        code = 429
    assert em._quota_error(E()) and em._quota_error(Exception("429 RESOURCE_EXHAUSTED"))
    assert not em._quota_error(Exception("400 INVALID_ARGUMENT"))
