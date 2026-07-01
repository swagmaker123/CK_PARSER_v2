from bs4 import BeautifulSoup


def extract_article_text(html):
    soup = BeautifulSoup(html, "html.parser")

    wrapper = soup.select_one(".article_text_wrapper")
    if wrapper:
        paragraphs = [
            p.get_text(" ", strip=True)
            for p in wrapper.find_all("p", class_="doc__text")
            if len(p.get_text(strip=True)) > 5
        ]
        if paragraphs:
            return "\n\n".join(paragraphs)

    body = (
        soup.select_one(".doc__body")
        or soup.select_one("[itemprop='articleBody']")
        or soup.select_one(".b-article__text")
    )

    if not body:
        meta = soup.find("meta", {"name": "description"}) or soup.find(
            "meta",
            {"property": "og:description"},
        )
        if meta and meta.get("content"):
            return meta["content"].strip()
        return ""

    for tag in body.select(
        ".incut, .doc__authors, .doc__tags, .doc__share, "
        "script, style, .adv, [class*='advert'], [class*='banner']"
    ):
        tag.decompose()

    paragraphs = [
        p.get_text(" ", strip=True)
        for p in body.find_all(["p", "h2", "h3", "li"])
        if len(p.get_text(strip=True)) > 10
    ]

    if paragraphs:
        return "\n\n".join(paragraphs)

    return body.get_text("\n", strip=True)
