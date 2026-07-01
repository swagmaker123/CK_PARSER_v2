# config/sources/garant.py

SOURCE_ID = "garant"
BASE_URL = "https://www.garant.ru"
SITEMAP_INDEX_URL = "https://www.garant.ru/sitemap.xml"
DEFAULT_DAYS = 30
REQUEST_DELAY = 0.3
TARGET_NEWS_COUNT = 2000
PAGE_FETCH_WORKERS = 5

NAMESPACE = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
