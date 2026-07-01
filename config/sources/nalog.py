# config/sources/nalog.py

SOURCE_ID = "nalog"
BASE_URL = "https://www.nalog.gov.ru/rn77/news/news_fta/"
DEFAULT_DAYS = 30
REQUEST_DELAY = 0.3
MAX_PAGES = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}
