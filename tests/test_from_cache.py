import datetime

from export.from_cache import cache_key_in_range, load_ck_cache_articles


def test_cache_key_in_range_interfax_format():
    today = datetime.date(2026, 7, 5)
    assert cache_key_in_range("interfax", "2026/07/05", 30, today)
    assert not cache_key_in_range("interfax", "2026-07-05", 30, today)


def test_cache_key_in_range_kommersant_format():
    today = datetime.date(2026, 7, 5)
    assert cache_key_in_range("kommersant", "2026-07-05", 30, today)
    assert not cache_key_in_range("kommersant", "2026/07/05", 30, today)


def test_cache_key_in_range_default_iso_format():
    today = datetime.date(2026, 7, 5)
    assert cache_key_in_range("banki", "2026-07-01", 30, today)
    assert not cache_key_in_range("banki", "2026-05-01", 30, today)


def test_load_ck_cache_articles_banki_does_not_raise():
    articles = load_ck_cache_articles("banki", "payment_systems", 30)
    assert isinstance(articles, list)
