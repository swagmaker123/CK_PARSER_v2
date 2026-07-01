# parsers/minfin/parser.py

import datetime
import re
import time
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config.sources import minfin as minfin_config
from parsers.base import FilteredParserBase


class MinfinParser(FilteredParserBase):
    """Парсер minfin.gov.ru — пресс-центр с постраничной навигацией."""

    def __init__(self):
        self._init_source(minfin_config.SOURCE_ID, "days")
        self.base_url = minfin_config.BASE_URL
        self.list_url = minfin_config.LIST_URL
        self.request_delay = minfin_config.REQUEST_DELAY
        self.max_pages = minfin_config.MAX_PAGES

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

    def _parse_minfin_date(self, raw: str) -> Optional[datetime.date]:
        raw = self._normalize_whitespace(raw)
        for fmt in ("%d.%m.%y", "%d.%m.%Y", "%d.%m.%y%H:%M", "%d.%m.%Y%H:%M"):
            try:
                return datetime.datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        match = re.search(r"\b(\d{2}\.\d{2}\.\d{2,4})\b", raw)
        if match:
            value = match.group(1)
            for fmt in ("%d.%m.%y", "%d.%m.%Y"):
                try:
                    return datetime.datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
        return None

    def _parse_listing_html(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        items: list[dict] = []

        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            title = self._normalize_whitespace(a.get_text(" ", strip=True))

            if not href or not title:
                continue
            if "/ru/press-center/" not in href and "id_4=" not in href:
                continue

            abs_url = urljoin(self.base_url, href)

            container_text = ""
            parent = a.parent
            if parent:
                container_text = self._normalize_whitespace(parent.get_text(" ", strip=True))

            pub_date = self._parse_minfin_date(container_text)
            if pub_date is None:
                continue

            items.append({"date": pub_date, "title": title, "url": abs_url})

        # Дедуп
        unique: dict[str, dict] = {}
        for item in items:
            unique[item["url"]] = item
        return list(unique.values())

    def _collect_listing_items(self, days: int) -> list[dict]:
        start_date = datetime.date.today() - datetime.timedelta(days=days)
        collected: list[dict] = []

        for page in range(self.max_pages):
            if page == 0:
                url = self.list_url
            else:
                url = f"https://minfin.gov.ru/RU/PRESS-CENTER/?TYPE_ID_4%5B%5D=1&offset_4={page * 20}"

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
            if oldest_date_on_page < start_date:
                break

            time.sleep(self.request_delay)

        # Дедуп
        unique: dict[str, dict] = {}
        for item in collected:
            unique[item["url"]] = item
        return list(unique.values())

    def _extract_full_text(self, url: str) -> str:
        response = self.http.get(url, context=url)
        if response is None:
            return ""

        try:
            soup = BeautifulSoup(response.text, "lxml")
            for selector in ["article", ".news-detail", ".press-detail", ".content", ".b-detail", "main"]:
                block = soup.select_one(selector)
                if block:
                    paragraphs = [
                        self._normalize_whitespace(p.get_text(" ", strip=True))
                        for p in block.find_all("p")
                    ]
                    paragraphs = [p for p in paragraphs if p]
                    if paragraphs:
                        return "\n".join(paragraphs)

            paragraphs = [
                self._normalize_whitespace(p.get_text(" ", strip=True))
                for p in soup.find_all("p")
            ]
            paragraphs = [p for p in paragraphs if p]
            return "\n".join(paragraphs)
        except Exception as e:
            self.stats.parse_failed += 1
            self._record_failure("parse", url, str(e))
            self._log("error", "Ошибка извлечения текста %s: %s", url, str(e))
            return ""

    # ------------------------------------------------------------------
    # _fetch_day_raw
    # ------------------------------------------------------------------

    def _fetch_day_raw(self, date_str, seen_urls):
        target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        all_items = self._collect_listing_items(days=30)

        day_items = [item for item in all_items if item.get("date") == target_date]

        self._log("info", "Ссылок за %s: %s", date_str, len(day_items))

        raw_items = []
        day_parse_failed = 0
        day_duplicate_skipped = 0

        for item in day_items:
            url = item.get("url", "")
            title = item.get("title", "")

            if url in seen_urls:
                self.stats.duplicate_skipped += 1
                day_duplicate_skipped += 1
                continue

            seen_urls.add(url)

            full_text = self._extract_full_text(url)

            if not full_text:
                self.stats.parse_failed += 1
                day_parse_failed += 1
                self._record_failure("parse", url, "пустой текст")
                continue

            title = title.strip()
            if not title:
                self.stats.empty_title += 1
                self._record_failure("empty_title", url, "пустой заголовок")
                continue

            raw_items.append({"url": url, "title": title, "date": date_str, "text": full_text})
            time.sleep(self.request_delay)

        self._log(
            "info",
            "%s: собрано %s | parse дроп %s | дубликаты %s",
            date_str, len(raw_items), day_parse_failed, day_duplicate_skipped,
        )

        return raw_items, len(day_items)

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def run(self, ck_profiles, days=None, refresh_days=0, logger=None, log_file=None, stats=None):
        if days is None:
            days = self.export_config.get("days", minfin_config.DEFAULT_DAYS)

        refresh_days = max(0, refresh_days or 0)
        self._setup_runtime(logger, log_file, stats=stats)

        today = datetime.date.today()
        raw_cache = self._load_raw_cache()
        ck_caches = self._prepare_ck_caches(ck_profiles)
        ck_results = {ck_id: [] for ck_id in ck_profiles}
        fetch_seen_urls = set()
        seen_urls_by_ck = {ck_id: set() for ck_id in ck_profiles}
        seen_titles_by_ck = {ck_id: set() for ck_id in ck_profiles}

        total_links = 0
        cached_days = 0

        self._log("info", "========== МИНФИН ==========")
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
                raw_items, links_count = self._fetch_day_raw(date_str, fetch_seen_urls)
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

        self._log("info", "========== МИНФИН ГОТОВО ==========")
        self._log("info", "Дней из сырого кэша: %s", cached_days)
        self._log("info", "Всего найдено ссылок: %s", total_links)

        for ck_id in ck_profiles:
            self._log("info", "ЦК %s: %s статей", ck_id, len(ck_results[ck_id]))

        return ck_results
