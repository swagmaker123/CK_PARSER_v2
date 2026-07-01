# parsers/cbr/parser.py

import datetime
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config.sources import cbr as cbr_config
from parsers.base import FilteredParserBase


class CbrParser(FilteredParserBase):
    """Парсер cbr.ru — RSS-ленты пресс-релизов и событий."""

    def __init__(self):
        self._init_source(cbr_config.SOURCE_ID, "days")
        self.base_url = cbr_config.BASE_URL
        self.rss_urls = cbr_config.RSS_URLS
        self.request_delay = cbr_config.REQUEST_DELAY

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

    def _parse_rss_date(self, raw_value: str) -> Optional[datetime.date]:
        raw_value = self._normalize_whitespace(raw_value)
        if not raw_value:
            return None
        try:
            return parsedate_to_datetime(raw_value).date()
        except Exception:
            pass
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(raw_value, fmt).date()
            except ValueError:
                continue
        return None

    def _parse_rss_feed(self, rss_url: str) -> list[dict]:
        """Парсит одну RSS-ленту, возвращает список dict."""
        response = self.http.get(rss_url, context=f"RSS {rss_url}")
        if response is None:
            self._record_failure("archive", rss_url, "RSS не загружена")
            return []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            self.stats.parse_failed += 1
            self._record_failure("parse", rss_url, f"XML: {e}")
            self._log("error", "XML parse error for %s: %s", rss_url, e)
            return []

        items = []
        for item in root.findall(".//item"):
            title = self._normalize_whitespace(item.findtext("title", default=""))
            link = self._normalize_whitespace(item.findtext("link", default=""))
            pub_date_raw = self._normalize_whitespace(item.findtext("pubDate", default=""))
            description = self._normalize_whitespace(item.findtext("description", default=""))

            pub_date = self._parse_rss_date(pub_date_raw)
            if not title or not link or not pub_date:
                continue

            items.append({
                "date": pub_date,
                "title": title,
                "url": urljoin(self.base_url, link),
                "description": description,
            })

        self._log("debug", "RSS %s: %s items", rss_url, len(items))
        return items

    def _collect_rss_items(self) -> list[dict]:
        """Собирает из всех RSS-лент, дедуплицирует по URL."""
        collected = []
        seen = set()

        for rss_url in self.rss_urls:
            for item in self._parse_rss_feed(rss_url):
                url = item["url"]
                if url not in seen:
                    seen.add(url)
                    collected.append(item)

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
        all_items = self._collect_rss_items()

        day_items = [item for item in all_items if item.get("date") == target_date]

        self._log("info", "RSS за %s: %s записей", date_str, len(day_items))

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

            raw_items.append({
                "url": url,
                "title": title,
                "date": date_str,
                "text": full_text,
            })

            time.sleep(self.request_delay)

        self._log(
            "info",
            "%s: собрано %s | parse дроп %s | дубликаты %s",
            date_str,
            len(raw_items),
            day_parse_failed,
            day_duplicate_skipped,
        )

        return raw_items, len(day_items)

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def run(self, ck_profiles, days=None, refresh_days=0, logger=None, log_file=None, stats=None):
        if days is None:
            days = self.export_config.get("days", cbr_config.DEFAULT_DAYS)

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

        self._log("info", "========== ЦБР ==========")
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

        self._log("info", "========== ЦБР ГОТОВО ==========")
        self._log("info", "Дней из сырого кэша: %s", cached_days)
        self._log("info", "Всего найдено ссылок: %s", total_links)

        for ck_id in ck_profiles:
            self._log("info", "ЦК %s: %s статей", ck_id, len(ck_results[ck_id]))

        return ck_results
