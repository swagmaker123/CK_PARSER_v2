import datetime
import os

from common.articles import dedupe_articles
from common.cache import JsonCache
from common.paths import PROJECT_ROOT

SOURCE_CACHE_KEYS = {
    "consultant": "reviews",
}

SOURCE_DATE_KEY_FORMATS = {
    "interfax": "%Y/%m/%d",
    "kommersant": "%Y-%m-%d",
}


def _cache_root_key(source_id):
    return SOURCE_CACHE_KEYS.get(source_id, "days")


def _cache_key_in_range(source_id, key, days, today):
    date_format = SOURCE_DATE_KEY_FORMATS.get(source_id)
    if date_format:
        valid_dates = {
            (today - datetime.timedelta(days=i)).strftime(date_format)
            for i in range(days)
        }
        return key in valid_dates

    cutoff = today - datetime.timedelta(days=days)
    try:
        review_date = datetime.datetime.strptime(key, "%Y-%m-%d").date()
    except ValueError:
        return False

    return review_date >= cutoff


def load_ck_cache_articles(source_id, ck_id, days):
    root_key = _cache_root_key(source_id)
    cache_path = os.path.join(
        PROJECT_ROOT,
        "cache",
        source_id,
        ck_id,
        "cache.json",
    )
    cache = JsonCache(cache_path, root_key).load()
    today = datetime.date.today()
    articles = []

    for key, entry in cache.get(root_key, {}).items():
        if not _cache_key_in_range(source_id, key, days, today):
            continue

        items = entry.get("items") or entry.get("articles") or []
        articles.extend(items)

    return dedupe_articles(articles)


def load_all_from_cache(sources, ck_profiles, days):
    combined_by_ck = {ck_id: {} for ck_id in ck_profiles}

    for source_id in sources:
        for ck_id in ck_profiles:
            combined_by_ck[ck_id][source_id] = load_ck_cache_articles(
                source_id,
                ck_id,
                days,
            )

    return combined_by_ck
