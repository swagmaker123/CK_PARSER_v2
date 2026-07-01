# parsers/nalog/parser.py

import datetime
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config.sources import nalog as nalog_config
from parsers.base import FilteredParserBase


class NalogParser(FilteredParserBase):
    """Парсер nalog.gov.ru — новости ФНС с постраничной навигацией и фильтром по дате."""

    def __init__(self):
        self._init_source(nalog_config.SOURCE_ID, "days")
        self.base_url = nalog_config.BASE_URL
        self.request_delay = nalog_config.REQUEST_DELAY
        self.max_pages = nalog_config.MAX_PAGES
        self.headers = nalog_config.HEADERS

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
    def _parse_news_date(date_str: str):
        """Парсит строку с датой."""
        if not date_str:
            return None
        date_str = date_str.strip()
        if re.match(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", date_str):
            return datetime.datetime.strptime(date_str, "%d.%m.%Y %H:%M").date()
        if re.match(r"\d{2}\.\d{2}\.\d{4}", date_str):
            return datetime.datetime.strptime(date_str, "%d.%m.%Y").date()
        return None

    def _collect_listing_items(self, days: int) -> list[dict]:
        """Собирает новости со страниц ФНС с фильтром по дате."""
        now = datetime.datetime.now()
        date_limit = now - datetime.timedelta(days=days)

        date_from_str = date_limit.strftime("%d.%m.%Y")
        date_to_str = now.strftime("%d.%m.%Y")

        base_params = (
            f"?n=&fd={date_from_str}&td={date_to_str}"
            "&th=0,591527,591526,591528,591529,592228"
            "&chFederal=true&rbAllRegions=true&rbRegionSelected=false&ddlRegion=3288"
        )

        collected = []
        seen_urls = set()

        for current_page in range(1, self.max_pages + 1):
            page_url = self.base_url + f"{current_page}.html" + base_params
            self._log("info", "Страница %s: %s", current_page, page_url)

            response = self.http.get(page_url, context=f"page {current_page}")
            if response is None:
                self._record_failure("archive", page_url, f"страница {current_page} не загружена")
                continue

            if response.status_code == 404:
                self._log("info", "Страница %s не найдена (404), завершаем", current_page)
                break

            soup = BeautifulSoup(response.text, "html.parser")

            news_blocks = soup.find_all("div", class_="news-block__text")
            if not news_blocks:
                news_blocks_alt = soup.find_all("div", class_="news-block")
                extracted = []
                for block in news_blocks_alt:
                    text_block = block.find("div", class_="news-block__text")
                    if text_block:
                        extracted.append(text_block)
                news_blocks = extracted

            if not news_blocks:
                self._log("info", "На странице %s нет блоков новостей. Завершаем.", current_page)
                break

            page_has_recent = False

            for block in news_blocks:
                try:
                    date_elem = block.find("div", class_="news__time")
                    if not date_elem:
                        continue

                    news_date_str = date_elem.get_text(strip=True)
                    news_date = self._parse_news_date(news_date_str)
                    if not news_date or news_date < date_limit.date():
                        continue

                    page_has_recent = True

                    title_elem = block.find("div", class_="news-block__name")
                    if not title_elem:
                        continue

                    link_elem = title_elem.find("a")
                    if not link_elem:
                        continue

                    title = link_elem.get_text(strip=True)
                    href = link_elem.get("href", "")
                    if not title or not href:
                        continue

                    news_url = urljoin(page_url, href) if href.startswith("/") else href

                    if news_url in seen_urls:
                        continue
                    seen_urls.add(news_url)

                    collected.append({"date": news_date, "title": title, "url": news_url})

                except Exception as e:
                    self._log("error", "Ошибка обработки блока: %s", str(e))
                    continue

            if not page_has_recent and current_page > 1:
                self._log("info", "Нет свежих новостей, завершаем")
                break

            time.sleep(self.request_delay)

        return collected

    def _extract_full_text(self, url: str) -> str:
        """Извлекает полный текст новости со страницы."""
        response = self.http.get(url, context=url)
        if response is None:
            return ""

        try:
            soup = BeautifulSoup(response.text, "html.parser")
            full_text = ""

            content_selectors = [
                ("div", "text_block"),
                ("div", "page-content__center"),
                ("div", "news-detail__text"),
                ("div", "article-text"),
                ("div", "news-text"),
                ("div", "content-text"),
                ("article", None),
            ]

            for tag, class_name in content_selectors:
                if class_name:
                    content_div = soup.find(tag, class_=class_name)
                else:
                    content_div = soup.find(tag)

                if content_div:
                    paragraphs = content_div.find_all("p")
                    full_text = " ".join(
                        p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
                    )
                    if full_text:
                        break

            if full_text:
                full_text = re.sub(r"Дата публикации:\s*\d{2}\.\d{2}\.\d{4}\s*", "", full_text)
                full_text = re.sub(
                    r"Дата публикации:\s*\d{2}\.\d{2}\.\d{4}\s*\d{2}:\d{2}\s*", "", full_text
                )
                full_text = re.sub(
                    r"Это архивная публикация - она может содержать устаревшую информацию\.\s*",
                    "", full_text,
                )
                full_text = re.sub(r"\s+", " ", full_text).strip()
                full_text = re.sub(r"&nbsp;", " ", full_text)
                full_text = re.sub(r"&[a-z]+;", "", full_text)

            return full_text
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
            days = self.export_config.get("days", nalog_config.DEFAULT_DAYS)

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

        self._log("info", "========== ФНС ==========")
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

        self._log("info", "========== ФНС ГОТОВО ==========")
        self._log("info", "Дней из сырого кэша: %s", cached_days)
        self._log("info", "Всего найдено ссылок: %s", total_links)

        for ck_id in ck_profiles:
            self._log("info", "ЦК %s: %s статей", ck_id, len(ck_results[ck_id]))

        return ck_results
