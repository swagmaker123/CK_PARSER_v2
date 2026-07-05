def dedupe_articles(articles, seen_urls=None, seen_titles=None):
    """Убирает дубликаты по URL и заголовку."""
    if seen_urls is None:
        seen_urls = set()
    if seen_titles is None:
        seen_titles = set()

    unique = []

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
