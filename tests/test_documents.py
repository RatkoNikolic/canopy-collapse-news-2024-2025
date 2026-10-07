from canopy_news.documents import cyrillic_share, extract, paragraph_offsets, to_latin

PAGE = """<html><head><title>Х</title>
<meta name="description" content="Пад надстрешнице у Новом Саду.">
<script type="application/ld+json">{"@type":"NewsArticle","headline":"Пад надстрешнице","datePublished":"2024-11-01T13:00:00+01:00"}</script>
</head><body><nav>Почетна | Вести | Спорт</nav>
<article><h1>Пад надстрешнице</h1>
<p>Надстрешница Железничке станице у Новом Саду срушила се у петак у 11.52 часова.</p>
<p>Спасилачке екипе раде на терену, а број повређених још није познат.</p>
<p>Влада је прогласила дан жалости. Џон и Љубица су били сведоци.</p>
</article><footer>Сва права задржана</footer></body></html>"""


def test_transliteration_and_script():
    assert to_latin("Љубица и Џон, Њиш") == "Ljubica i Džon, Njiš"
    assert cyrillic_share("Нови Сад") == 1.0 and cyrillic_share("Novi Sad") == 0.0


def test_paragraph_offsets():
    body = "prvi\n\ndrugi pasus\ntreci"
    offs = paragraph_offsets(body)
    assert [body[a:b] for a, b in offs] == ["prvi", "drugi pasus", "treci"]


def test_extract_cyrillic_page():
    d = extract(PAGE.encode(), "https://www.rts.rs/lat/vesti/drustvo/5600000/pad.html")
    assert d["error"] is None
    assert d["script"] == "cyrl" and d["section"] == "vesti"
    assert "Nadstrešnica Železničke stanice" in d["body"]
    assert d["body_original"].startswith("Надстрешница")
    assert "Sport" not in d["body"]  # navigation is not article text
    a, b = d["para_offsets"][0]
    assert d["body"][a:b].startswith("Nadstrešnica")


def test_outlet_rules():
    from canopy_news.documents import _apply_line_rules, load_rules

    rules = load_rules()
    assert "container" in rules["informer"]
    body = "Prvi pasus.\nOglas\nDrugi pasus.\nKoje je vaše mišljenje o ovoj temi?\nNAJČITANIJE"
    assert _apply_line_rules(body, rules["n1"]) == "Prvi pasus.\nDrugi pasus."
    page = b"""<html><body><h1>Naslov</h1><div class="teasers"><p>Druga vest koja ne pripada clanku, sa dosta teksta da bude paragraf.</p></div>
    <div class="single-news-content"><p>Pravi tekst clanka je ovde i dovoljno je dug da bude izvucen.</p>
    <p>Drugi pasus pravog clanka takodje ima dovoljno teksta za ekstrakciju.</p></div></body></html>"""
    d = extract(page, "https://informer.rs/vesti/1/x", rules["informer"])
    assert "Pravi tekst" in d["body"] and "Druga vest" not in d["body"]


def test_dedupe_parts(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from canopy_news.documents import dedupe_parts
    for k, ids in enumerate((["a", "b"], ["b", "c"])):
        pq.write_table(pa.table({"event_id": ids, "x": [k] * 2}), tmp_path / f"part-{k}.parquet")
    assert dedupe_parts(tmp_path) == {"rows": 3, "dropped": 1}
    files = list(tmp_path.glob("part-*.parquet"))
    assert len(files) == 1 and sorted(pq.read_table(files[0])["event_id"].to_pylist()) == ["a", "b", "c"]
    assert dedupe_parts(tmp_path) == {"rows": 3, "dropped": 0}


def test_exclusive(tmp_path):
    import pytest
    from chrono_harness import Layout

    from canopy_news.config import exclusive
    lay = Layout(tmp_path).ensure()
    with exclusive(lay, "documents"):
        with pytest.raises(SystemExit):
            with exclusive(lay, "documents"):
                pass
    with exclusive(lay, "documents"):
        pass


def test_line_rules_match_latin_form_and_keep_commas(tmp_path):
    from canopy_news.documents import _apply_line_rules, load_rules
    csv = tmp_path / "extraction.csv"
    csv.write_text('outlet_id,rule,value,reason\nrts,drop_line,"Izvor:\\s*.{1,80}",header line\n')
    rules = load_rules(csv)["rts"]
    assert rules["drop_line"] == ["Izvor:\\s*.{1,80}"]          # the comma inside {1,80} survives
    body = "Извор: РТС\nПрави текст чланка.\nIzvor:\xa0Tanjug"
    assert _apply_line_rules(body, rules) == "Прави текст чланка."


def test_soft_404():
    from canopy_news.documents import soft_404
    art = "https://www.b92.net/info/politika/108055/niski-opozicionari/vest"
    assert soft_404(art, "https://www.b92.net/info/politika")
    assert not soft_404(art, art) and not soft_404(art, None)
    assert not soft_404(art, "https://www.b92.net/info/politika/108055/drugi-slug/vest")
    assert not soft_404("https://www.b92.net/info/politika", "https://www.b92.net/info")  # no id asked
    assert soft_404("https://pink.rs/politika/650001/naslov", "https://pink.rs/")
