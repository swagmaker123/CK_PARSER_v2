# parsers/banki/parser.py

import datetime
import re
import time
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config.sources import banki as banki_config
from parsers.base import FilteredParserBase


class BankiParser(FilteredParserBase):
    """Парсер banki.ru — лента новостей с постраничной навигацией.

    Архитектура (bulk cache):
      1. _collect_listing_items(earliest_date) — один раз обходит ВСЕ страницы ленты за окно
      2. _ensure_bulk_cache() — один раз скачивает все статьи, группирует по дате
      3. _fetch_day_raw() — отдаёт из _bulk_cache, не ходит в сеть
    """

    def __init__(self):
        self._init_source(banki_config.SOURCE_ID, "days")
        self.base_url = banki_config.BASE_URL
        self.list_url = banki_config.LIST_URL
        self.request_delay = banki_config.REQUEST_DELAY
        self.max_pages = banki_config.MAX_PAGES
        self.digest_exceptions = banki_config.DIGEST_EXCEPTIONS

        # Единый кеш прогона: {date_str: [article_dict, ...]}
        self._bulk_cache: dict[str, list[dict]] | None = None

    # ------------------------------------------------------------------
    # Trim-методы
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
    # Вспомогательные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _parse_listing_html(self, html: str) -> list[dict]:
        """Парсит HTML-страницу ленты, извлекает дату, заголовок, ссылку."""
        try:
            soup = BeautifulSoup(html, "lxml")
            text = soup.get_text("\n", strip=True)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
        except Exception:
            return []

        items: list[dict] = []
        current_date: Optional[datetime.date] = None
        i = 0

        while i < len(lines):
            line = lines[i]

            if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", line):
                try:
                    current_date = datetime.datetime.strptime(line, "%d.%m.%Y").date()
                except ValueError:
                    current_date = None
                i += 1
                continue

            if current_date and re.fullmatch(r"\d{2}:\d{2}", line):
                title = lines[i + 1] if i + 1 < len(lines) else ""
                if title:
                    items.append({
                        "date": current_date,
                        "title": self._normalize_whitespace(title),
                        "url": None,
                        "preview_text": "",
                    })
                i += 2
                continue

            i += 1

        # Мэтчим ссылки из <a> по заголовку
        title_to_index: dict[str, int] = {}
        for idx, item in enumerate(items):
            title_to_index.setdefault(item["title"], idx)

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            title = self._normalize_whitespace(a.get_text(" ", strip=True))

            if not title:
                continue

            if "/news/lenta/?id=" in href or "/news/lenta/" in href:
                abs_url = urljoin(self.base_url, href)
                idx = title_to_index.get(title)
                if idx is not None and items[idx]["url"] is None:
                    items[idx]["url"] = abs_url

        return [
            item for item in items
            if item.get("date") and item.get("title") and item.get("url")
        ]

    def _collect_listing_items(self, earliest_date: datetime.date) -> list[dict]:
        """Обходит страницы ленты, возвращает список dict с date/title/url.

        earliest_date — самый ранний день окна.
        Идём по страницам, пока не выйдем за earliest_date.
        """
        collected: list[dict] = []

        for page in range(1, self.max_pages + 1):
            url = self.list_url if page <= 1 else f"{self.list_url}?page={page}"

            response = self.http.get(url, context=f"listing page {page}")
            if response is None:
                self._record_failure("archive", url, "страница листинга не загружена")
                break

            page_items = self._parse_listing_html(response.text)
            if not page_items:
                break

            collected.extend(page_items)

            page_dates = [item["date"] for item in page_items if item.get("date")]
            if not page_dates:
                break

            oldest_date_on_page = min(page_dates)
            if oldest_date_on_page < earliest_date:
                break

            self._log(
                "info", "  Страница %s: %s статей, до %s",
                page, len(page_items), oldest_date_on_page,
            )

            time.sleep(self.request_delay)

        self._log("info", "Листинг: собрано %s записей", len(collected))
        return collected

    def _extract_full_text(self, url: str) -> str:
        """Извлекает полный текст статьи по URL."""
        response = self.http.get(url, context=url)
        if response is None:
            return ""

        try:
            soup = BeautifulSoup(response.text, "lxml")
            article = soup.find("article") or soup.find("main") or soup
            paragraphs = [
                self._normalize_whitespace(p.get_text(" ", strip=True))
                for p in article.find_all("p")
            ]
            paragraphs = [p for p in paragraphs if p]
            full_text = "\n".join(paragraphs)
            # Отрезаем служебный блок
            full_text = full_text.split("Читать по теме", 1)[0].rstrip()
            return full_text
        except Exception as e:
            self.stats.parse_failed += 1
            self._record_failure("parse", url, str(e))
            self._log("error", "Ошибка извлечения текста %s: %s", url, str(e))
            return ""

    # ------------------------------------------------------------------
    # Единая загрузка: листинг → все статьи → группировка по датам
    # ------------------------------------------------------------------

    def _ensure_bulk_cache(self, earliest_date: datetime.date, seen_urls: set):
        """
        Скачивает листинг + все статьи ОДИН раз за весь прогон.
        Группирует статьи по date в self._bulk_cache.
        earliest_date — самый ранний день окна (today - days).
        """
        if self._bulk_cache is not None:
            return

        self._bulk_cache = {}

        # 1. Собираем ссылки из листинга (один раз)
        listing_items = self._collect_listing_items(earliest_date)
        total_items = len(listing_items)

        if total_items == 0:
            self._log("info", "Листинг: нет записей для загрузки")
            return

        self._log("info", "Единоразовая загрузка %s статей", total_items)

        # 2. Скачиваем все статьи, группируем по дате
        by_date: dict[str, list[dict]] = {}
        parse_drops = 0
        duplicates = 0
        empty_title = 0

        for i, item in enumerate(listing_items):
            url = item.get("url", "")
            title = item.get("title", "")
            pub_date = item.get("date")

            if not url or url in seen_urls:
                duplicates += 1
                continue

            seen_urls.add(url)

            title = title.strip()
            if not title:
                empty_title += 1
                continue

            # Отбрасываем дайджесты
            is_digest = any(d in title.lower() for d in self.digest_exceptions)
            if is_digest:
                continue

            full_text = self._extract_full_text(url)

            if not full_text:
                parse_drops += 1
                self._record_failure("parse", url, "пустой текст")
                continue

            date_key = pub_date.strftime("%Y-%m-%d")
            by_date.setdefault(date_key, []).append({
                "url": url, "title": title, "date": date_key, "text": full_text,
            })

            # Прогресс каждые 20 статей
            if (i + 1) % 20 == 0:
                self._log("info", "  Загружено %s / %s статей", i + 1, total_items)

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
        При первом вызове загружает листинг + все статьи один раз,
        затем отдаёт статьи из кеша по дате.
        earliest_date — самый ранний день окна, нужен для листинга.
        """
        if earliest_date is None:
            earliest_date = datetime.date.today() - datetime.timedelta(days=30)

        self._ensure_bulk_cache(earliest_date, seen_urls)

        day_items = self._bulk_cache.get(date_str, [])
        return day_items, len(day_items)

    # ------------------------------------------------------------------
    # Основной публичный метод
    # ------------------------------------------------------------------

    def run(self, ck_profiles, days=None, refresh_days=0, logger=None, log_file=None, stats=None):
        if days is None:
            days = self.export_config.get("days", banki_config.DEFAULT_DAYS)

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

        self._log("info", "========== BANKI.RU ==========")
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

                self._log(
                    "info",
                    "Сырой кэш (ссылок было: %s, статей %s)",
                    links_count,
                    len(raw_items),
                )
            else:
                if force_refresh and cached_day is not None:
                    self._log("info", "Пересбор дня (refresh-days)")

                raw_items, links_count = self._fetch_day_raw(
                    date_str, fetch_seen_urls, earliest_date=earliest_date,
                )
                self._set_cache_entry(
                    raw_cache,
                    date_str,
                    raw_items,
                    links_count=links_count,
                )

            total_links += links_count

            self._log("info", "Фильтрация по ЦК:")
            day_results = self._apply_all_ck_filters(
                raw_items,
                ck_profiles,
                ck_caches,
                date_str,
                links_count,
            )

            for ck_id, day_articles in day_results.items():
                unique = self._dedupe_articles(
                    day_articles,
                    seen_urls_by_ck[ck_id],
                    seen_titles_by_ck[ck_id],
                )
                ck_results[ck_id].extend(unique)

        self._trim_cache(raw_cache, days, today)
        self._save_raw_cache(raw_cache)
        self._trim_ck_caches(ck_caches, days, today)
        self._save_ck_caches(ck_caches)

        self._log("info", "========== BANKI.RU ГОТОВО ==========")
        self._log("info", "Дней из сырого кэша: %s", cached_days)
        self._log("info", "Всего найдено ссылок: %s", total_links)

        for ck_id in ck_profiles:
            self._log("info", "ЦК %s: %s статей", ck_id, len(ck_results[ck_id]))

        return ck_results
