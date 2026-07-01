import datetime
import time
import re

from bs4 import BeautifulSoup

from config.sources import interfax as interfax_config
from parsers.base import FilteredParserBase


class InterfaxParser(FilteredParserBase):
    def __init__(self):
        self._init_source(interfax_config.SOURCE_ID, "days")
        self.base_url = interfax_config.BASE_URL
        self.request_delay = interfax_config.REQUEST_DELAY
        self.archive_sections = interfax_config.ARCHIVE_SECTIONS

    def _trim_cache(self, cache, days, today):
        valid_dates = {
            (today - datetime.timedelta(days=i)).strftime("%Y/%m/%d")
            for i in range(days)
        }
        self.raw_cache.trim(cache, lambda key: key in valid_dates)

    def _trim_ck_caches(self, ck_caches, days, today):
        valid_dates = {
            (today - datetime.timedelta(days=i)).strftime("%Y/%m/%d")
            for i in range(days)
        }

        for entry in ck_caches.values():
            entry["obj"].trim(entry["data"], lambda key: key in valid_dates)

    def _extract_article_links(self, soup):
        links = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]

            if not any(section in href for section in self.archive_sections):
                continue

            parts = href.strip("/").split("/")

            if not parts:
                continue

            if not parts[-1].isdigit():
                continue

            full_url = (
                self.base_url + href
                if href.startswith("/")
                else href
            )

            links.add(full_url)

        return links

    def _get_archive_page_urls(self, date_str, first_page_soup):
        page_urls = [f"{self.base_url}/news/{date_str}/"]
        page_numbers = set()

        for a in first_page_soup.find_all("a", href=True):
            href = a["href"]
            match = re.search(
                rf"/news/{re.escape(date_str)}/page_(\d+)",
                href,
            )
            if match:
                page_numbers.add(int(match.group(1)))

        for page_num in sorted(page_numbers):
            if page_num == 1:
                continue
            page_urls.append(
                f"{self.base_url}/news/{date_str}/page_{page_num}"
            )

        return page_urls

    def get_news_links_for_date(self, date_str):
        links = set()

        first_url = f"{self.base_url}/news/{date_str}/"
        response = self.http.get(first_url, context=date_str)

        if response is None:
            self._record_failure(
                "archive",
                first_url,
                "не загружена первая страница архива",
            )
            return []

        first_soup = BeautifulSoup(response.text, "html.parser")
        page_urls = self._get_archive_page_urls(date_str, first_soup)
        self._log(
            "info",
            "%s: страниц архива %s",
            date_str,
            len(page_urls),
        )

        for page_index, page_url in enumerate(page_urls):
            if page_index == 0:
                soup = first_soup
            else:
                time.sleep(self.request_delay)
                page_response = self.http.get(
                    page_url,
                    context=f"{date_str} {page_url}",
                )
                if page_response is None:
                    if self.stats is not None:
                        self.stats.archive_pages_failed += 1
                    self._record_failure(
                        "archive",
                        page_url,
                        "страница архива не загружена",
                    )
                    continue
                soup = BeautifulSoup(page_response.text, "html.parser")

            page_links = self._extract_article_links(soup)
            links.update(page_links)
            self._log(
                "debug",
                "%s: страница %s/%s, ссылок +%s",
                date_str,
                page_index + 1,
                len(page_urls),
                len(page_links),
            )

        return list(links)

    def parse_article(self, url):
        time.sleep(self.request_delay)

        response = self.http.get(url)

        if response is None:
            return None

        try:
            soup = BeautifulSoup(response.text, "html.parser")

            title_tag = soup.find("h1")
            title = (
                title_tag.get_text(strip=True)
                if title_tag
                else ""
            )

            date_meta = soup.find(
                "meta",
                itemprop="datePublished",
            )

            date = (
                date_meta.get("content")
                if date_meta
                else ""
            )

            article_body = soup.find(
                "article",
                itemprop="articleBody",
            )

            text = ""

            if article_body:
                for tag in article_body.find_all(
                    ["script", "style", "aside"]
                ):
                    tag.decompose()

                text = article_body.get_text(
                    separator="\n",
                    strip=True,
                )

                text = re.sub(r"\s+", " ", text)

                if title and text.startswith(title):
                    text = text[len(title):].strip()

                text = re.sub(
                    r"^.*?INTERFAX\.RU\s*-\s*",
                    "",
                    text,
                )

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

    def _fetch_day_raw(self, date_str, seen_urls):
        links = self.get_news_links_for_date(date_str)

        self._log("info", "Найдено ссылок: %s", len(links))

        raw_items = []
        day_http_failed = 0
        day_parse_failed = 0
        day_duplicate_skipped = 0

        for link in links:
            if link in seen_urls:
                self.stats.duplicate_skipped += 1
                day_duplicate_skipped += 1
                continue

            seen_urls.add(link)

            http_failed_before = self.stats.http_failed
            parse_failed_before = self.stats.parse_failed

            article = self.parse_article(link)

            if not article:
                if self.stats.http_failed > http_failed_before:
                    day_http_failed += 1
                elif self.stats.parse_failed > parse_failed_before:
                    day_parse_failed += 1
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

        return raw_items, len(links)

    def run(self, ck_profiles, days=None, refresh_days=0, logger=None, log_file=None, stats=None):
        if days is None:
            days = self.export_config.get(
                "days",
                interfax_config.DEFAULT_DAYS,
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

        self._log("info", "========== INTERFAX ==========")
        self._log("info", "Парсим последние %s дней", days)
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
            date_str = current_date.strftime("%Y/%m/%d")

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

        self._log("info", "========== INTERFAX ГОТОВО ==========")
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
