from canopy_news.documents import extract
from canopy_news.verify import compare

PAGE = b"""<html><head><title>T</title></head><body><article><h1>T</h1>
<p>Prvi pasus clanka sa dovoljno teksta da ga ekstraktor prepozna kao telo clanka.</p>
<p>Drugi pasus clanka, takodje sa dovoljno teksta za ekstrakciju i poredjenje.</p>
</article></body></html>"""


def _stored(page=PAGE):
    d = extract(page, "https://example.rs/vesti/1/t")
    return {"event_id": "e", "unit_id": "https://example.rs/vesti/1/t", "outlet_id": "x",
            "body_hash": d["body_hash"], "body": d["body"]}


def test_compare_outcomes():
    s = _stored()
    assert compare(s, 200, PAGE, {})["outcome"] == "unchanged"
    edited = compare(s, 200, PAGE.replace(b"Drugi pasus", b"Izmenjen pasus"), {})
    assert edited["outcome"] == "edited" and 0.8 < edited["similarity"] < 1
    assert compare(s, 404, b"", {})["outcome"] == "gone"
    assert compare(s, 503, b"", {})["outcome"] == "failed"
