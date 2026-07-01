# config/sources/rbc.py

SOURCE_ID = "rbc"
BASE_URL = "https://www.rbc.ru"
API_URL = "https://www.rbc.ru/api/rbcnews/v1/newsfeed"
DEFAULT_DAYS = 30
REQUEST_DELAY = 0.3
MAX_API_REQUESTS = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.rbc.ru/short_news",
}
