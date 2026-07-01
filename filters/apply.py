def normalize_news_item(item):
    if not isinstance(item, dict):
        return {}

    return {
        "url": item.get("url", ""),
        "title": item.get("title", ""),
        "date": item.get("date") or item.get("review_date", ""),
        "text": item.get("text", ""),
        "matched_keyword": item.get("matched_keyword") or item.get("category", ""),
    }


def build_search_text(item):
    return f"{item.get('title', '')} {item.get('text', '')}"


def apply_filter(items, compiled_filter, normalize_fn=normalize_news_item):
    filtered = []

    for item in items:
        row = normalize_fn(item)
        search_text = build_search_text(row)

        if not compiled_filter.matches_keywords(search_text):
            continue

        row["matched_keyword"] = compiled_filter.format_matched_keywords(search_text)
        filtered.append(row)

    return filtered
