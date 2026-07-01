# config/sources/palata.py

SOURCE_ID = "palata"
BASE_URL = "https://palata-nk.ru"
LIST_URL = "https://palata-nk.ru/about/news/?day=all&PAGEN_1="
DEFAULT_DAYS = 30
REQUEST_DELAY = 0.5

MONTH_MAP = {
    "января": "01", "февраля": "02", "марта": "03",
    "апреля": "04", "мая": "05", "июня": "06",
    "июля": "07", "августа": "08", "сентября": "09",
    "октября": "10", "ноября": "11", "декабря": "12",
}
