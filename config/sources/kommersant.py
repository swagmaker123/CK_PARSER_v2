SOURCE_ID = "kommersant"
BASE_URL = "https://www.kommersant.ru"
ARCHIVE_URL = "https://www.kommersant.ru/archive/news/day/{date}"
DEFAULT_DAYS = 30
ARCHIVE_DATE_FORMAT = "%Y-%m-%d"
ARTICLE_DELAY = 0.2
DAY_DELAY = 0.2

SEL_MORE = ".js-archive-more-button"

JS_COLLECT = """
() => {
    const results = [];
    document.querySelectorAll('.uho__text.rubric_lenta__item_text').forEach(c => {
        const l = c.querySelector('.uho__link');
        const d = c.querySelector('.uho__tag');
        if (l) results.push({
            date:  d ? d.textContent.trim() : '',
            title: l.textContent.trim(),
            url:   l.href
        });
    });
    return results;
}
"""

PLAYWRIGHT_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]
PAGE_GOTO_TIMEOUT = 30000
PAGE_WAIT_MS = 1000
SCROLL_WAIT_MS = 400
BUTTON_WAIT_MS = 1500
SCROLL_ATTEMPTS = 6
EMPTY_STREAK_LIMIT = 2
CLICK_TIMEOUT = 8000
AFTER_CLICK_WAIT_MS = 200
AFTER_CLICK_POLLS = 25
BEFORE_CLICK_WAIT_MS = 800

ARTICLE_HEADERS = {
    "Referer": "https://www.kommersant.ru/",
}
