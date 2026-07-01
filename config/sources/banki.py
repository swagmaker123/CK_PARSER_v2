# config/sources/banki.py

SOURCE_ID = "banki"
BASE_URL = "https://www.banki.ru"
LIST_URL = "https://www.banki.ru/news/lenta/"
DEFAULT_DAYS = 30
REQUEST_DELAY = 0.3
MAX_PAGES = 20

DIGEST_EXCEPTIONS = ("за неделю", "за день", "лучшие статьи недели", "новости недели")
