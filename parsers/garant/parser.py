# parsers/garant/parser.py

import datetime
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from bs4 import BeautifulSoup

from config.sources import garant as garant_config
from parsers.base import FilteredParserBase


class GarantParser(FilteredParserBase):
    """Парсер garant.ru — через sitemap, единая загрузка за прогон."""

    def __init__(self):
        self._init_source(garant_config.SOURCE_ID, "days")
        self.base_url = garant_config.BASE_URL
        self.sitemap_index_url = garant_config.SITEMAP_INDEX_URL
        self.request_delay = garant_config.REQUEST_DELAY
        self.target_news_count = garant_config.TARGET_NEWS_COUNT
        self.page_fetch_workers = garant_config.PAGE_FETCH_WORKERS
        self.namespace = garant_config.NAMESPACE

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

    @staticmethod
    def _parse_sitemap_date(raw: str) -> Optional[datetime.date]:
        if not raw or not raw.strip():
            return None
        try:
            return datetime.datetime.fromisoformat(raw.strip()[:19]).date()
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Шаг 1: собрать ссылки из sitemap (один раз)
    # ------------------------------------------------------------------

    def _collect_news_links(self, start_date) -> list[dict]:
        """Собирает ссылки на статьи /news/{id}/ с lastmod >= start_date."""
        response = self.http.get(self.sitemap_index_url, context="sitemap index")
        if response is None:
            self._record_failure("archive", self.sitemap_index_url, "sitemap index не загружен")
            return []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            self.stats.parse_failed += 1
            self._record_failure("parse", self.sitemap_index_url, f"XML: {e}")
            self._log("error", "XML parse error in sitemap index: %s", e)
            return []

        sitemap_urls = []
        for sitemap in root.findall("ns:sitemap", self.namespace):
            loc_elem = sitemap.find("ns:loc", self.namespace)
            if loc_elem is not None:
                sitemap_urls.append(loc_elem.text)

        self._log("info", "Sitemap-ов в индексе: %s", len(sitemap_urls))

        news_links: list[dict] = []
        empty_sitemaps_in_row = 0

        for sitemap_url in sitemap_urls:
            resp = self.http.get(sitemap_url, context=f"sitemap {sitemap_url}")
            if resp is None:
                continue

            try:
                sitemap_root = ET.fromstring(resp.content)
            except ET.ParseError:
                continue

            batch: list[dict] = []
            for url_elem in sitemap_root.findall("ns:url", self.namespace):
                loc_elem = url_elem.find("ns:loc", self.namespace)
                if loc_elem is None:
                    continue

                link = loc_elem.text
                # Только статьи вида /news/{id}/
                if not re.search(r"/news/\d+/$", link or ""):
                    continue

                lastmod_elem = url_elem.find("ns:lastmod", self.namespace)
                lastmod_date = None
                if lastmod_elem is not None and lastmod_elem.text:
                    lastmod_date = self._parse_sitemap_date(lastmod_elem.text)

                # Берём только свежие (lastmod в окне) или без lastmod
                if lastmod_date is not None and lastmod_date < start_date:
                    continue

                batch.append({"url": link, "lastmod": lastmod_date})

            self._log("info", "  %s → %s ссылок", sitemap_url.split("/")[-1], len(batch))
            news_links.extend(batch)

            # Стоп: собрали достаточно
            if len(news_links) >= self.target_news_count:
                self._log("info", "Достгли лимита %s — останов", self.target_news_count)
                break

            # Стоп: 5 пустых sitemap подряд — значит дальше только старое
            if len(batch) == 0:
                empty_sitemaps_in_row += 1
                if empty_sitemaps_in_row >= 5:
                    self._log("info", "5 пустых sitemap подряд — останов")
                    break
            else:
                empty_sitemaps_in_row = 0

        self._log("info", "Всего ссылок из sitemap (после фильтра): %s", len(news_links))
        return news_links

    # ------------------------------------------------------------------
    # Шаг 2: скачать и распарсить страницу статьи
    # ------------------------------------------------------------------

    def _parse_news_page(self, url: str) -> Optional[dict]:
        """Извлекает заголовок, дату и текст со страницы новости."""
        response = self.http.get(url, context=url)
        if response is None:
            return None

        try:
            soup = BeautifulSoup(response.text, "lxml")

            title_tag = soup.find("h1")
            title = title_tag.get_text(strip=True) if title_tag else ""

            # Дата: <time datetime="..."> или ld+json datePublished
            pub_date = None
            time_tag = soup.find("time", attrs={"datetime": True})
            if time_tag:
                try:
                    pub_date = datetime.datetime.fromisoformat(time_tag["datetime"]).date()
                except ValueError:
                    pass

            if pub_date is None:
                ld = soup.find("script", type="application/ld+json")
                if ld:
                    import json
                    try:
                        data = json.loads(ld.string)
                        dp = data.get("datePublished")
                        if dp:
                            pub_date = datetime.datetime.fromisoformat(str(dp)[:19]).date()
                    except (ValueError, TypeError, json.JSONDecodeError):
                        pass

            paragraphs = []
            clearfix_elements = soup.select(".clearfix ul, .clearfix p")
            paragraphs.extend(p.get_text(strip=True) for p in clearfix_elements)
            text = "\n\n".join(paragraphs) if paragraphs else ""

            return {"date": pub_date, "title": title, "text": text, "url": url}
        except Exception as e:
            self.stats.parse_failed += 1
            self._record_failure("parse", url, str(e))
            self._log("error", "Ошибка разбора %s: %s", url, str(e))
            return None

    # ------------------------------------------------------------------
    # Единая загрузка: sitemap → все страницы → группировка по датам
    # ------------------------------------------------------------------

    def _ensure_bulk_cache(self, earliest_date, seen_urls):
        """
        Скачивает sitemap + все страницы ОДИН раз за весь прогон.
        Группирует статьи по pub_date в self._bulk_cache.
        earliest_date — самый ранний день окна (today - days).
        """
        if self._bulk_cache is not None:
            return

        self._bulk_cache = {}

        # 1. Собираем ссылки из sitemap
        news_links = self._collect_news_links(earliest_date)
        total_links = len(news_links)

        if total_links == 0:
            self._log("info", "Нет ссылок для загрузки")
            return

        self._log("info", "Единоразовая загрузка %s страниц с %s workers", total_links, self.page_fetch_workers)

        # 2. Скачиваем все страницы, группируем по pub_date
        by_date: dict[str, list[dict]] = {}
        parse_drops = 0
        no_date = 0
        duplicates = 0

        with ThreadPoolExecutor(max_workers=self.page_fetch_workers) as executor:
            futures = {
                executor.submit(self._parse_news_page, link["url"]): link["url"]
                for link in news_links
            }

            for future in as_completed(futures):
                url = futures[future]

                try:
                    page_data = future.result()
                except Exception:
                    parse_drops += 1
                    continue

                if page_data is None:
                    parse_drops += 1
                    continue

                # Дубликаты
                page_url = page_data.get("url", url)
                if page_url in seen_urls:
                    duplicates += 1
                    continue
                seen_urls.add(page_url)

                # Дата
                pub_date = page_data.get("date")
                if pub_date is None:
                    no_date += 1
                    continue

                # Заголовок
                title = page_data.get("title", "").strip()
                if not title:
                    self.stats.empty_title += 1
                    continue

                # Текст (может быть пустым — всё равно берём)
                text = page_data.get("text", "")

                date_key = pub_date.strftime("%Y-%m-%d")
                by_date.setdefault(date_key, []).append({
                    "url": page_url, "title": title, "date": date_key, "text": text,
                })

        self._bulk_cache = by_date

        self._log(
            "info",
            "Загрузка завершена: %s статей по %s датам | дроп: %s | без даты: %s | дубль: %s",
            sum(len(v) for v in by_date.values()),
            len(by_date),
            parse_drops, no_date, duplicates,
        )

    # ------------------------------------------------------------------
    # _fetch_day_raw — отдаёт из bulk-кеша, не ходит в сеть
    # ------------------------------------------------------------------

    def _fetch_day_raw(self, date_str, seen_urls, earliest_date=None):
        """
        Вызывается из run() для каждого дня.
        При первом вызове загружает sitemap + все страницы один раз,
        затем отдаёт статьи из кеша по дате.
        earliest_date — самый ранний день окна, нужен для фильтрации sitemap.
        """
        if earliest_date is None:
            # Fallback: используем текущий день (не идеально, но безопасно)
            earliest_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        self._ensure_bulk_cache(earliest_date, seen_urls)

        raw_items = self._bulk_cache.get(date_str, [])
        # total_links = общее число ссылок, которые мы скачали из sitemap
        total_links = sum(len(v) for v in self._bulk_cache.values()) if self._bulk_cache else 0

        self._log("info", "%s: собрано %s", date_str, len(raw_items))

        return raw_items, total_links

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def run(self, ck_profiles, days=None, refresh_days=0, logger=None, log_file=None, stats=None):
        if days is None:
            days = self.export_config.get("days", garant_config.DEFAULT_DAYS)

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

        self._log("info", "========== ГАРАНТ ==========")
        self._log("info", "Парсим последние %s дней", days)
        if refresh_days:
            self._log("info", "Пересбор без кэша: последние %s дн. от сегодня", refresh_days)
        self._log("info", "ЦК: %s", ", ".join(ck_profiles))
        self._log("info", "Сырой кэш: %s", self.raw_cache_file)

        # Самый ранний день окна — нужен для единоразовой загрузки sitemap
        earliest_date = today - datetime.timedelta(days=days - 1)

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

        self._log("info", "========== ГАРАНТ ГОТОВО ==========")
        self._log("info", "Дней из сырого кэша: %s", cached_days)
        self._log("info", "Всего найдено ссылок: %s", total_links)

        for ck_id in ck_profiles:
            self._log("info", "ЦК %s: %s статей", ck_id, len(ck_results[ck_id]))

        return ck_results
