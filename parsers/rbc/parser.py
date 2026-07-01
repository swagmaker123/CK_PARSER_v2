# parsers/rbc/parser.py

import datetime
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config.sources import rbc as rbc_config
from parsers.base import FilteredParserBase


class RbcParser(FilteredParserBase):
    """Парсер rbc.ru — JSON API + парсинг статей.

    Архитектура (bulk cache):
      1. _collect_api_items() — один раз собирает ВСЕ ссылки из API за окно
      2. _ensure_bulk_cache() — один раз скачивает все страницы, группирует по дате
      3. _fetch_day_raw() — отдаёт из _bulk_cache, не ходит в сеть
    """

    def __init__(self):
        self._init_source(rbc_config.SOURCE_ID, "days")
        self.base_url = rbc_config.BASE_URL
        self.api_url = rbc_config.API_URL
        self.request_delay = rbc_config.REQUEST_DELAY
        self.max_api_requests = rbc_config.MAX_API_REQUESTS
        self.headers = rbc_config.HEADERS

        # Единый кеш прогона: {date_str: [article_dict, ...]}
        self._bulk_cache: dict[str, list[dict]] | None = None

    # ------------------------------------------------------------------
    # Trim
    # ------------------------------------------------------------------

    def _trim_cache(self, cache, days, today):
        valid_dates = {
            (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(days)
        }
        self.raw_cache.trim(cache, lambda key: key in valid_dates)

    def _trim_ck_caches(self, ck_caches, days, today):
        valid_dates = {
            (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(days)
        }
        for entry in ck_caches.values():
            entry["obj"].trim(entry["data"], lambda key: key in valid_dates)

    # ------------------------------------------------------------------
    # Вспомогательные
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    # ------------------------------------------------------------------
    # Шаг 1: собрать все ссылки из API (один раз)
    # ------------------------------------------------------------------

    def _collect_api_items(self, earliest_date: datetime.date) -> list[dict]:
        """Собирает элементы из RBC API с пагинацией.

        earliest_date — самый ранний день окна (today - days).
        Идём по страницам, пока не выйдем за earliest_date.
        """
        date_limit = int(
            datetime.datetime.combine(earliest_date, datetime.time.min).timestamp()
        )

        self._log(
            "info", "API: фильтруем с %s",
            earliest_date.strftime("%Y-%m-%d"),
        )

        collected = []
        end_cursor = None
        request_count = 0

        while request_count < self.max_api_requests:
            params = {"limit": 20}
            if end_cursor:
                params["endCursor"] = end_cursor

            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{self.api_url}?{query}"

            response = self.http.get(
                url,
                context=f"API request {request_count + 1}",
            )

            if response is None:
                break

            try:
                data = response.json()
            except Exception as e:
                self.stats.parse_failed += 1
                self._record_failure("parse", self.api_url, f"JSON: {e}")
                break

            items = data.get("items", [])
            if not items:
                break

            oldest_ts = min(item.get("publishDateT", 0) for item in items)

            for item in items:
                pub_ts = item.get("publishDateT", 0)
                if pub_ts < date_limit:
                    continue

                title = item.get("title", "")
                publish_date = datetime.datetime.fromtimestamp(pub_ts).date()
                item_url = item.get("url", "")

                collected.append({
                    "date": publish_date,
                    "title": title,
                    "url": item_url,
                })

            # Если самый старый элемент в пачке старше окна — стоп
            if oldest_ts < date_limit:
                self._log("info", "API: достигнут предел дат — останов")
                break

            if not data.get("moreExists", False):
                break

            end_cursor = data.get("endCursor")
            request_count += 1
            time.sleep(self.request_delay)

        self._log(
            "info", "API: собрано %s записей за %s запросов",
            len(collected), request_count,
        )
        return collected

    # ------------------------------------------------------------------
    # Шаг 2: скачать и распарсить страницу статьи
    # ------------------------------------------------------------------

    def _extract_full_text(self, url: str) -> str:
        """Извлекает полный текст статьи по URL."""
        absolute_url = urljoin(self.base_url, url)
        response = self.http.get(absolute_url, context=absolute_url)
        if response is None:
            return ""

        try:
            soup = BeautifulSoup(response.text, "html.parser")

            article_body = soup.find("div", class_="article__text")
            if article_body:
                paragraphs = article_body.find_all("p")
                full_text = " ".join(
                    p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
                )
                if full_text:
                    return full_text

            paragraphs = soup.find_all("p", class_="paragraph")
            full_text = " ".join(
                p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
            )
            if full_text:
                return full_text

            anons_span = soup.find("span", class_="js-article-pro-anons-text")
            if anons_span:
                full_text = anons_span.get_text(strip=True)
                if full_text:
                    return full_text

            return ""
        except Exception as e:
            self.stats.parse_failed += 1
            self._record_failure("parse", absolute_url, str(e))
            self._log("error", "Ошибка извлечения текста %s: %s", absolute_url, str(e))
            return ""

    def _fetch_and_parse_page(self, url: str, title: str, pub_date: datetime.date) -> Optional[dict]:
        """Скачивает страницу и возвращает готовый article dict."""
        full_text = self._extract_full_text(url)
        return {
            "date": pub_date.strftime("%Y-%m-%d"),
            "title": title.strip(),
            "text": full_text,
            "url": url,
        }

    # ------------------------------------------------------------------
    # Единая загрузка: API → все страницы → группировка по датам
    # ------------------------------------------------------------------

    def _ensure_bulk_cache(self, earliest_date: datetime.date, seen_urls: set):
        """
        Скачивает API + все страницы ОДИН раз за весь прогон.
        Группирует статьи по date в self._bulk_cache.
        earliest_date — самый ранний день окна (today - days).
        """
        if self._bulk_cache is not None:
            return

        self._bulk_cache = {}

        # 1. Собираем ссылки из API (один раз, ~100 запросов вместо 3000)
        api_items = self._collect_api_items(earliest_date)
        total_items = len(api_items)

        if total_items == 0:
            self._log("info", "API: нет записей для загрузки")
            return

        self._log("info", "Единоразовая загрузка %s страниц", total_items)

        # 2. Скачиваем все страницы, группируем по дате
        by_date: dict[str, list[dict]] = {}
        parse_drops = 0
        duplicates = 0
        empty_title = 0

        # Последовательная загрузка (RBC баннит при параллели)
        for i, item in enumerate(api_items):
            url = item.get("url", "")
            title = item.get("title", "")
            pub_date = item.get("date")

            if not url or url in seen_urls:
                duplicates += 1
                continue

            seen_urls.add(url)

            if not title.strip():
                empty_title += 1
                continue

            page_data = self._fetch_and_parse_page(url, title, pub_date)
            if page_data is None:
                parse_drops += 1
                continue

            date_key = page_data["date"]
            by_date.setdefault(date_key, []).append(page_data)

            # Прогресс каждые 100 страниц
            if (i + 1) % 100 == 0:
                self._log(
                    "info", "  Загружено %s / %s страниц",
                    i + 1, total_items,
                )

            time.sleep(self.request_delay)

        self._bulk_cache = by_date

        total_articles = sum(len(v) for v in by_date.values())
        self._log(
            "info",
            "Загрузка завершена: %s статей по %s датам | дроп: %s | дубль: %s | без заголовка: %s",
            total_articles, len(by_date),
            parse_drops, duplicates, empty_title,
        )

    # ------------------------------------------------------------------
    # _fetch_day_raw — отдаёт из bulk-кеша, не ходит в сеть
    # ------------------------------------------------------------------

    def _fetch_day_raw(self, date_str, seen_urls, earliest_date=None):
        """
        Вызывается из run() для каждого дня.
        При первом вызове загружает API + все страницы один раз,
        затем отдаёт статьи из кеша по дате.
        earliest_date — самый ранний день окна, нужен для API фильтрации.
        """
        if earliest_date is None:
            earliest_date = datetime.date.today() - datetime.timedelta(days=30)

        self._ensure_bulk_cache(earliest_date, seen_urls)

        day_items = self._bulk_cache.get(date_str, [])
        return day_items, len(day_items)

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def run(self, ck_profiles, days=None, refresh_days=0, logger=None, log_file=None, stats=None):
        if days is None:
            days = self.export_config.get("days", rbc_config.DEFAULT_DAYS)

        refresh_days = max(0, refresh_days or 0)
        self._setup_runtime(logger, log_file, stats=stats)

        today = datetime.date.today()
        earliest_date = today - datetime.timedelta(days=days - 1)

        raw_cache = self._load_raw_cache()
        ck_caches = self._prepare_ck_caches(ck_profiles)
        ck_results = {ck_id: [] for ck_id in ck_profiles}
        fetch_seen_urls = set()
        seen_urls_by_ck = {ck_id: set() for ck_id in ck_profiles}
        seen_titles_by_ck = {ck_id: set() for ck_id in ck_profiles}

        total_links = 0
        cached_days = 0

        self._log("info", "========== РБК ==========")
        self._log("info", "Парсим последние %s дней", days)
        if refresh_days:
            self._log("info", "Пересбор без кэша: последние %s дн. от сегодня", refresh_days)
        self._log("info", "ЦК: %s", ", ".join(ck_profiles))
        self._log("info", "Сырой кэш: %s", self.raw_cache_file)

        for i in range(days):
            current_date = today - datetime.timedelta(days=i)
            date_str = current_date.strftime("%Y-%m-%d")

            self._log("info", "=== %s ===", date_str)

            cached_day = self._get_cache_entry(raw_cache, date_str)
            force_refresh = i < refresh_days

            if cached_day is not None and not force_refresh:
                cached_days += 1
                raw_items = self._cache_entry_items(cached_day)
                links_count = self._cache_entry_links_count(cached_day)
                self._log("info", "Сырой кэш (ссылок: %s, статей: %s)", links_count, len(raw_items))
            else:
                if force_refresh and cached_day is not None:
                    self._log("info", "Пересбор дня (refresh-days)")
                raw_items, links_count = self._fetch_day_raw(
                    date_str, fetch_seen_urls, earliest_date=earliest_date,
                )
                self._set_cache_entry(raw_cache, date_str, raw_items, links_count=links_count)

            total_links += links_count

            self._log("info", "Фильтрация по ЦК:")
            day_results = self._apply_all_ck_filters(
                raw_items, ck_profiles, ck_caches, date_str, links_count,
            )

            for ck_id, day_articles in day_results.items():
                unique = self._dedupe_articles(
                    day_articles, seen_urls_by_ck[ck_id], seen_titles_by_ck[ck_id],
                )
                ck_results[ck_id].extend(unique)

        self._trim_cache(raw_cache, days, today)
        self._save_raw_cache(raw_cache)
        self._trim_ck_caches(ck_caches, days, today)
        self._save_ck_caches(ck_caches)

        self._log("info", "========== РБК ГОТОВО ==========")
        self._log("info", "Дней из сырого кэша: %s", cached_days)
        self._log("info", "Всего найдено ссылок: %s", total_links)

        for ck_id in ck_profiles:
            self._log("info", "ЦК %s: %s статей", ck_id, len(ck_results[ck_id]))

        return ck_results
