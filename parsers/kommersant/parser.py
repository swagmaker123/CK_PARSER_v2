import asyncio
import datetime
import time

from config.sources import kommersant as kommersant_config
from parsers.base import FilteredParserBase
from parsers.kommersant.article_text import extract_article_text
from parsers.kommersant.collector import collect_one_day


class KommersantParser(FilteredParserBase):
    def __init__(self):
        self._init_source(kommersant_config.SOURCE_ID, "days")
        self.article_delay = kommersant_config.ARTICLE_DELAY
        self.day_delay = kommersant_config.DAY_DELAY
        self.date_format = kommersant_config.ARCHIVE_DATE_FORMAT

    def _trim_cache(self, cache, days, today):
        valid_dates = {
            (today - datetime.timedelta(days=i)).strftime(self.date_format)
            for i in range(days)
        }
        self.raw_cache.trim(cache, lambda key: key in valid_dates)

    def _trim_ck_caches(self, ck_caches, days, today):
        valid_dates = {
            (today - datetime.timedelta(days=i)).strftime(self.date_format)
            for i in range(days)
        }

        for entry in ck_caches.values():
            entry["obj"].trim(entry["data"], lambda key: key in valid_dates)

    def parse_article(self, url, title="", date=""):
        time.sleep(self.article_delay)

        response = self.http.get(
            url,
            extra_headers=kommersant_config.ARTICLE_HEADERS,
        )

        if response is None:
            return None

        try:
            response.encoding = "utf-8"
            text = extract_article_text(response.text)

            if not title or not date:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(response.text, "html.parser")

                if not title:
                    title_tag = soup.find("h1", class_="doc_header__name")
                    if not title_tag:
                        title_tag = soup.find("h1", class_="article_name")
                    title = title_tag.get_text(strip=True) if title_tag else ""

                if not date:
                    date_tag = soup.find("time", class_="doc_header__publish_time")
                    if not date_tag:
                        date_tag = soup.find("time")
                    date = date_tag.get_text(strip=True) if date_tag else ""

            return {
                "url": url,
                "title": title,
                "date": date,
                "text": text,
            }

        except Exception as e:
            reason = str(e)
            if self.stats is not None:
                self.stats.parse_failed += 1
            self._record_failure("parse", url, reason)
            self._log("error", "разбор %s: %s", url, reason)
            return None

    async def _collect_day_items(self, date_str):
        return await collect_one_day(date_str, log_fn=self._log)

    def _fetch_day_raw(self, date_str, fetch_seen_urls):
        self._log("info", "Фаза 1: Playwright — сбор ссылок")
        link_items = asyncio.run(self._collect_day_items(date_str))
        time.sleep(self.day_delay)

        self._log("info", "Найдено ссылок: %s", len(link_items))
        self._log("info", "Фаза 2: парсинг текстов")

        raw_items = []
        day_http_failed = 0
        day_parse_failed = 0
        day_duplicate_skipped = 0

        for index, item in enumerate(link_items, 1):
            link = item.get("url", "")
            preview_title = item.get("title", "").strip()
            preview_date = item.get("date", "").strip()

            if not link:
                continue

            if link in fetch_seen_urls:
                self.stats.duplicate_skipped += 1
                day_duplicate_skipped += 1
                continue

            fetch_seen_urls.add(link)

            self._log(
                "debug",
                "[%s/%s] %s",
                index,
                len(link_items),
                preview_title[:70],
            )

            http_failed_before = self.stats.http_failed
            parse_failed_before = self.stats.parse_failed

            article = self.parse_article(
                link,
                title=preview_title,
                date=preview_date,
            )

            if not article:
                if self.stats.http_failed > http_failed_before:
                    day_http_failed += 1
                elif self.stats.parse_failed > parse_failed_before:
                    day_parse_failed += 1
                else:
                    day_http_failed += 1
                continue

            title = article["title"].strip()

            if not title:
                self.stats.empty_title += 1
                self._record_failure("empty_title", link, "пустой заголовок")
                self._log("warning", "пустой заголовок: %s", link)
                continue

            raw_items.append(article)

        self._log(
            "info",
            "%s: разобрано %s | HTTP дроп %s | parse дроп %s | дубликаты %s",
            date_str,
            len(raw_items),
            day_http_failed,
            day_parse_failed,
            day_duplicate_skipped,
        )

        return raw_items, len(link_items)

    def run(self, ck_profiles, days=None, refresh_days=0, logger=None, log_file=None, stats=None):
        if days is None:
            days = self.export_config.get(
                "days",
                kommersant_config.DEFAULT_DAYS,
            )

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

        self._log("info", "========== KOMMERSANT ==========")
        self._log("info", "Парсим последние %s дней (Playwright + HTTP)", days)
        if refresh_days:
            self._log(
                "info",
                "Пересбор без кэша: последние %s дн. от сегодня",
                refresh_days,
            )
        self._log("info", "ЦК: %s", ", ".join(ck_profiles))
        self._log("info", "Сырой кэш: %s", self.raw_cache_file)

        for i in range(days):
            current_date = today - datetime.timedelta(days=i)
            date_str = current_date.strftime(self.date_format)

            self._log("info", "=== %s ===", date_str)

            cached_day = self._get_cache_entry(raw_cache, date_str)
            force_refresh = i < refresh_days

            if cached_day is not None and not force_refresh:
                cached_days += 1
                raw_items = self._cache_entry_items(cached_day)
                links_count = self._cache_entry_links_count(cached_day)

                self._log(
                    "info",
                    "Сырой кэш (ссылок было: %s, статей: %s)",
                    links_count,
                    len(raw_items),
                )
            else:
                if force_refresh and cached_day is not None:
                    self._log("info", "Пересбор дня (refresh-days)")

                raw_items, links_count = self._fetch_day_raw(date_str, fetch_seen_urls)
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

        self._log("info", "========== KOMMERSANT ГОТОВО ==========")
        self._log("info", "Дней из сырого кэша: %s", cached_days)
        self._log("info", "Всего найдено ссылок: %s", total_links)

        for ck_id in ck_profiles:
            self._log(
                "info",
                "ЦК %s: %s статей",
                ck_id,
                len(ck_results[ck_id]),
            )

        return ck_results
