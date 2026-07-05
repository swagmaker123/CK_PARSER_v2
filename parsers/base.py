import os

from common.articles import dedupe_articles
from common.cache import JsonCache
from common.http_client import HttpClient
from common.logging import RunStats
from common.paths import PROJECT_ROOT
from export.writer import load_export_config
from filters.apply import apply_filter
from filters.engine import load_filter


class FilteredParserBase:
    def _init_source(self, source_id, cache_root_key):
        self.source_id = source_id
        self.cache_root_key = cache_root_key

        self.raw_cache_dir = os.path.join(PROJECT_ROOT, "cache", source_id, "raw")
        self.raw_cache_file = os.path.join(self.raw_cache_dir, "cache.json")
        self.export_config = load_export_config(source_id, None)

        self.logger = None
        self.log_file = None
        self.stats = None
        self.http = None
        self.raw_cache = JsonCache(
            self.raw_cache_file,
            cache_root_key,
            log_fn=self._log,
        )

        os.makedirs(self.raw_cache_dir, exist_ok=True)

    def _ck_cache(self, ck_id):
        cache_dir = os.path.join(PROJECT_ROOT, "cache", self.source_id, ck_id)
        os.makedirs(cache_dir, exist_ok=True)
        return JsonCache(
            os.path.join(cache_dir, "cache.json"),
            self.cache_root_key,
            log_fn=self._log,
        )

    def _log(self, level, message, *args):
        if self.logger is not None:
            getattr(self.logger, level)(message, *args)

    def _record_failure(self, kind, target, reason):
        if self.stats is not None:
            self.stats.record_failure(kind, target, reason)

    def _setup_runtime(self, logger, log_file, stats=None):
        self.logger = logger
        self.log_file = log_file
        self.stats = stats if stats is not None else RunStats()
        self.http = HttpClient(
            stats=self.stats,
            log_fn=self._log,
            record_failure_fn=self._record_failure,
        )

    def _load_raw_cache(self):
        return self.raw_cache.load()

    def _save_raw_cache(self, cache):
        self.raw_cache.save(cache)

    def _get_cache_entry(self, cache, key):
        return self.raw_cache.get(cache, key)

    def _set_cache_entry(self, cache, key, items, links_count=0, status="processed"):
        self.raw_cache.set_entry(
            cache,
            key,
            items,
            links_count=links_count,
            status=status,
        )

    @staticmethod
    def _cache_entry_items(entry):
        if not entry:
            return []
        return entry.get("items") or entry.get("articles") or []

    @staticmethod
    def _cache_entry_links_count(entry):
        if not entry:
            return 0
        return entry.get("links_found", 0)

    def _trim_cache(self, cache, keep_fn):
        self.raw_cache.trim(cache, keep_fn)

    def _prepare_ck_caches(self, ck_profiles):
        caches = {}

        for ck_id in ck_profiles:
            cache_obj = self._ck_cache(ck_id)
            caches[ck_id] = {
                "obj": cache_obj,
                "data": cache_obj.load(),
            }

        return caches

    def _save_ck_caches(self, ck_caches):
        for entry in ck_caches.values():
            entry["obj"].save(entry["data"])

    def _set_ck_cache_entry(self, cache_obj, cache_data, key, items, links_count=0):
        cache_obj.set_entry(
            cache_data,
            key,
            items,
            links_count=links_count,
        )

    def _apply_all_ck_filters(self, raw_items, ck_profiles, ck_caches, key, links_count):
        day_results = {}

        for ck_id in ck_profiles:
            compiled = load_filter(ck_id)
            filtered = apply_filter(raw_items, compiled)
            filter_skipped = len(raw_items) - len(filtered)

            if self.stats is not None:
                self.stats.filter_skipped += filter_skipped

            cache_entry = ck_caches[ck_id]
            self._set_ck_cache_entry(
                cache_entry["obj"],
                cache_entry["data"],
                key,
                filtered,
                links_count=links_count,
            )

            day_results[ck_id] = filtered
            self._log(
                "info",
                "  ЦК %s (%s): %s из %s",
                ck_id,
                compiled.profile.title,
                len(filtered),
                len(raw_items),
            )

        return day_results

    def _dedupe_articles(self, articles, seen_urls, seen_titles):
        return dedupe_articles(articles, seen_urls, seen_titles)
