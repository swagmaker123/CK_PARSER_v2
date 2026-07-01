# parsers/palata/parser.py

import datetime
import re
import time

from bs4 import BeautifulSoup

from config.sources import palata as palata_config
from parsers.base import FilteredParserBase


class PalataParser(FilteredParserBase):
    """Парсер palata-nk.ru — новости палаты с постраничной навигацией."""

    def __init__(self):
        self._init_source(palata_config.SOURCE_ID, "days")
        self.base_url = palata_config.BASE_URL
        self.list_url = palata_config.LIST_URL
        self.request_delay = palata_config.REQUEST_DELAY
        self.month_map = palata_config.MONTH_MAP

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

    def _parse_listing_page(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        news_cards = soup.select("div.news-item")
        items = []

        for card in news_cards:
            a_tag = card.select_one(".card-body a.link")
            if not a_tag:
                continue

            href = a_tag.get("href", "").strip()
            if not href:
                continue

            title = a_tag.get("title", "").strip()
            if not title:
                title = a_tag.get_text(strip=True)

            date_span = card.select_one(".card-footer span.text-primary")
            if not date_span:
                continue
            raw_date = date_span.get_text(strip=True)

            parts = raw_date.split()
            if len(parts) < 3:
                continue
            day_str, month_str, year_str = parts[0], parts[1], parts[2]
            month_num = self.month_map.get(month_str.lower())
            if not month_num:
                continue

            date_str = f"{day_str.zfill(2)}.{month_num}.{year_str}"
            try:
                pub_date = datetime.datetime.strptime(date_str, "%d.%m.%Y").date()
            except ValueError:
                continue

            url = self.base_url + href if href.startswith("/") else href

            items.append({"date": pub_date, "title": self._normalize_whitespace(title), "url": url})

        return items

    def _get_last_page_number(self) -> int:
        url = f"{self.list_url}1"
        response = self.http.get(url, context="pagination")
        if response is None:
            return 1

        soup = BeautifulSoup(response.text, "lxml")
        pagination_items = soup.select('.pagination li.page-item a[href*="PAGEN_1="]')

        page_numbers = []
        for link in pagination_items:
            href = link.get("href", "")
            match = re.search(r"PAGEN_1=(\d+)", href)
            if match:
                page_numbers.append(int(match.group(1)))

        return max(page_numbers) if page_numbers else 1

    def _collect_listing_items(self, days: int) -> list[dict]:
        start_date = datetime.date.today() - datetime.timedelta(days=days)
        end_date = datetime.date.today()
        last_page = self._get_last_page_number()
        collected = []

        self._log("info", "Всего страниц: %s", last_page)

        for page in range(1, last_page + 1):
            url = f"{self.list_url}{page}"
            response = self.http.get(url, context=f"page {page}")
            if response is None:
                continue

            page_items = self._parse_listing_page(response.text)
            if not page_items:
                break

            for item in page_items:
                if start_date <= item["date"] <= end_date:
                    collected.append(item)

            oldest_on_page = min(item["date"] for item in page_items)
            if oldest_on_page < start_date:
                break

            time.sleep(self.request_delay)

        return collected

    def _extract_full_text(self, url: str) -> str:
        response = self.http.get(url, context=url)
        if response is None:
            return ""

        try:
            soup = BeautifulSoup(response.text, "lxml")
            content_div = soup.select_one("div.article__content")
            if not content_div:
                article = soup.find("article")
                content_div = article if article else soup

            full_text = content_div.get_text(separator=" ", strip=True)
            return self._normalize_whitespace(full_text)
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
            days = self.export_config.get("days", palata_config.DEFAULT_DAYS)

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

        self._log("info", "========== ПАЛАТА НК ==========")
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

        self._log("info", "========== ПАЛАТА НК ГОТОВО ==========")
        self._log("info", "Дней из сырого кэша: %s", cached_days)
        self._log("info", "Всего найдено ссылок: %s", total_links)

        for ck_id in ck_profiles:
            self._log("info", "ЦК %s: %s статей", ck_id, len(ck_results[ck_id]))

        return ck_results
