import datetime
import os

from common.cache import JsonCache
from common.paths import PROJECT_ROOT

SOURCE_CACHE_KEYS = {
    "interfax": "days",
    "kommersant": "days",
    "consultant": "reviews",
}


def _cache_key_in_range(source_id, key, days, today):
    if source_id in ("interfax", "kommersant"):
        valid_dates = {
            (today - datetime.timedelta(days=i)).strftime("%Y/%m/%d")
            for i in range(days)
        }
        return key in valid_dates

    cutoff = today - datetime.timedelta(days=days)
    try:
        review_date = datetime.datetime.strptime(key, "%Y-%m-%d").date()
    except ValueError:
        return False

    return review_date >= cutoff


def _dedupe_articles(articles):
    unique = []
    seen_urls = set()
    seen_titles = set()

    for article in articles:
        url = article.get("url", "")
        title = article.get("title", "").strip()

        if url in seen_urls or title in seen_titles:
            continue

        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)

        unique.append(article)

    return unique


def load_ck_cache_articles(source_id, ck_id, days):
    root_key = SOURCE_CACHE_KEYS[source_id]
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

    return _dedupe_articles(articles)


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
