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
