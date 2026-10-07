from canopy_news.idprobe import article_id, classify


def test_article_id():
    assert article_id("https://pink.rs/zadruga/640287/boza-i-aneli") == 640287
    assert article_id("https://informer.rs/politika/vesti/996934/x") == 996934
    assert article_id("https://pink.rs/404") is None


def test_classify():
    page = '<link rel="canonical" href="https://pink.rs/vesti/650001/naslov"/>'
    assert classify(page, 200) == "https://pink.rs/vesti/650001/naslov"
    assert classify('<link rel="canonical" href="https://pink.rs/404"/>', 200) is None
    assert classify("<html>no canonical</html>", 200) is None
    assert classify(page, 404) is None
