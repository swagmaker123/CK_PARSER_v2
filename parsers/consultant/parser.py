import datetime
import re
import time

from bs4 import BeautifulSoup

from config.sources import consultant as consultant_config
from parsers.base import FilteredParserBase


class ConsultantParser(FilteredParserBase):
    def __init__(self):
        self._init_source(consultant_config.SOURCE_ID, "reviews")
        self.base_url = consultant_config.BASE_URL
        self.archive_url = consultant_config.ARCHIVE_URL
        self.target_categories = consultant_config.TARGET_CATEGORIES
        self.review_delay = consultant_config.REVIEW_DELAY

    def _trim_cache(self, cache, days, today):
        cutoff = today - datetime.timedelta(days=days)
        self.raw_cache.trim(
            cache,
            lambda key: self._parse_review_date(key) >= cutoff,
        )

    def _trim_ck_caches(self, ck_caches, days, today):
        cutoff = today - datetime.timedelta(days=days)

        for entry in ck_caches.values():
            entry["obj"].trim(
                entry["data"],
                lambda key: self._parse_review_date(key) >= cutoff,
            )

    @staticmethod
    def _parse_review_date(date_str):
        return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()

    def get_review_links(self, days):
        links = []
        seen_urls = set()

        response = self.http.get(self.archive_url, context="archive")

        if response is None:
            self._record_failure(
                "archive",
                self.archive_url,
                "не загружен архив обзоров",
            )
            return links

        soup = BeautifulSoup(response.text, "html.parser")
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/law/review/fed/fw" not in href or not href.endswith(".html"):
                continue

            date_match = re.search(r"fw(\d{4}-\d{2}-\d{2})", href)
            if not date_match:
                continue

            review_date = datetime.datetime.strptime(date_match.group(1), "%Y-%m-%d")
            if review_date < cutoff:
                continue

            url = self.base_url + href if href.startswith("/") else href
            if url in seen_urls:
                continue

            seen_urls.add(url)
            links.append({"url": url, "date": date_match.group(1)})

        links.sort(key=lambda item: item["date"], reverse=True)
        self._log("info", "Найдено выпусков обзоров: %s", len(links))
        return links

    def parse_review(self, review_info):
        url = review_info["url"]
        date = review_info["date"]
        results = []

        response = self.http.get(url, context=f"review {date}")

        if response is None:
            return results

        try:
            response.encoding = "utf-8"
            soup = BeautifulSoup(response.text, "html.parser")
            current_category = None

            for element in soup.find_all(["h3", "p"]):
                text = element.get_text(strip=True)
                upper_text = text.upper()

                if element.name == "h3" or (
                    element.name == "p"
                    and element.find("strong")
                    and upper_text in self.target_categories
                ):
                    if upper_text in self.target_categories:
                        current_category = upper_text
                        self._log("debug", "  Категория: %s", current_category)
                    else:
                        found = False
                        for cat in self.target_categories:
                            if cat in upper_text:
                                current_category = cat
                                found = True
                                break
                        if not found and element.name == "h3":
                            current_category = None

                if not current_category:
                    continue

                doc_link = element.find("a", href=True)
                if not doc_link or "cons_doc_LAW" not in doc_link["href"]:
                    continue

                doc_title = doc_link.get_text(strip=True)
                if len(doc_title) <= 30:
                    continue

                news_title = ""
                news_text = ""
                next_node = element.find_next_sibling()
                first_paragraph = True

                while next_node and next_node.name not in ["h3", "hr"]:
                    inner_link = next_node.find("a", href=True)
                    if inner_link and "cons_doc_LAW" in inner_link["href"]:
                        break

                    paragraph_text = next_node.get_text(strip=True)
                    if paragraph_text:
                        if first_paragraph and next_node.find("strong"):
                            news_title = paragraph_text
                            first_paragraph = False
                        else:
                            news_text += paragraph_text + "\n"
                            first_paragraph = False

                    next_node = next_node.find_next_sibling()

                if not news_title and news_text:
                    paragraphs = news_text.split("\n")
                    news_title = paragraphs[0]
                    news_text = "\n".join(paragraphs[1:])

                href = doc_link["href"]
                full_link = href if href.startswith("http") else self.base_url + href

                results.append(
                    {
                        "url": full_link,
                        "title": news_title,
                        "date": date,
                        "text": news_text.strip(),
                    }
                )
                self._log("debug", "    + %s", news_title[:50])

        except Exception as e:
            reason = str(e)
            if self.stats is not None:
                self.stats.parse_failed += 1
            self._record_failure("parse", url, reason)
            self._log("error", "разбор %s: %s", url, reason)

        return results

    def _days_since_review(self, review_date_str, today):
        review_date = self._parse_review_date(review_date_str)
        return (today - review_date).days

    def run(self, ck_profiles, days=None, refresh_days=0, logger=None, log_file=None, stats=None):
        if days is None:
            days = self.export_config.get(
                "days",
                consultant_config.DEFAULT_DAYS,
            )

        refresh_days = max(0, refresh_days or 0)

        self._setup_runtime(logger, log_file, stats=stats)

        today = datetime.date.today()
        raw_cache = self._load_raw_cache()
        ck_caches = self._prepare_ck_caches(ck_profiles)
        ck_results = {ck_id: [] for ck_id in ck_profiles}
        seen_urls_by_ck = {ck_id: set() for ck_id in ck_profiles}
        seen_titles_by_ck = {ck_id: set() for ck_id in ck_profiles}

        cached_reviews = 0
        total_parsed = 0

        self._log("info", "========== CONSULTANT ==========")
        self._log("info", "Consultant: обзоры за %s дней", days)
        if refresh_days:
            self._log(
                "info",
                "Пересбор без кэша: выпуски за последние %s дн.",
                refresh_days,
            )
        self._log("info", "ЦК: %s", ", ".join(ck_profiles))
        self._log("info", "Сырой кэш: %s", self.raw_cache_file)

        reviews = self.get_review_links(days)

        for review in reviews:
            review_date = review["date"]
            self._log("info", "=== обзор %s ===", review_date)

            cached_review = self._get_cache_entry(raw_cache, review_date)
            force_refresh = self._days_since_review(review_date, today) < refresh_days

            if cached_review is not None and not force_refresh:
                cached_reviews += 1
                raw_items = self._cache_entry_items(cached_review)
                links_count = self._cache_entry_links_count(cached_review)

                self._log(
                    "info",
                    "Сырой кэш (записей было: %s)",
                    len(raw_items),
                )
            else:
                if force_refresh and cached_review is not None:
                    self._log("info", "Пересбор выпуска (refresh-days)")

                raw_items = self.parse_review(review)
                total_parsed += len(raw_items)
                links_count = len(raw_items)

                self._set_cache_entry(
                    raw_cache,
                    review_date,
                    raw_items,
                    links_count=links_count,
                )

                self._log("info", "Разобрано записей: %s", len(raw_items))
                time.sleep(self.review_delay)

            self._log("info", "Фильтрация по ЦК:")
            day_results = self._apply_all_ck_filters(
                raw_items,
                ck_profiles,
                ck_caches,
                review_date,
                links_count,
            )

            for ck_id, review_items in day_results.items():
                unique = self._dedupe_articles(
                    review_items,
                    seen_urls_by_ck[ck_id],
                    seen_titles_by_ck[ck_id],
                )
                ck_results[ck_id].extend(unique)

        self._trim_cache(raw_cache, days, today)
        self._save_raw_cache(raw_cache)
        self._trim_ck_caches(ck_caches, days, today)
        self._save_ck_caches(ck_caches)

        self._log("info", "========== CONSULTANT ГОТОВО ==========")
        self._log("info", "Выпусков из сырого кэша: %s", cached_reviews)
        self._log("info", "Разобрано записей: %s", total_parsed)

        for ck_id in ck_profiles:
            self._log(
                "info",
                "ЦК %s: %s статей",
                ck_id,
                len(ck_results[ck_id]),
            )

        return ck_results
