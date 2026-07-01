import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.browser import (
    BACKOFF_429,
    HEADERS,
    REQUEST_TIMEOUT,
    RETRY_5XX_BACKOFF,
    RETRY_5XX_TOTAL,
)


class HttpClient:
    def __init__(self, stats=None, log_fn=None, record_failure_fn=None):
        self.stats = stats
        self.log_fn = log_fn or (lambda *args, **kwargs: None)
        self.record_failure_fn = record_failure_fn or (lambda *args, **kwargs: None)
        self.headers = HEADERS

        self.session = requests.Session()

        retry = Retry(
            total=RETRY_5XX_TOTAL,
            backoff_factor=RETRY_5XX_BACKOFF,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)

        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get(self, url, context="", extra_headers=None):
        label = context or url
        headers = self.headers
        if extra_headers:
            headers = {**self.headers, **extra_headers}

        for attempt in range(len(BACKOFF_429) + 1):
            if attempt > 0:
                delay = BACKOFF_429[attempt - 1]
                if self.stats is not None:
                    self.stats.http_429_retries += 1
                self.log_fn(
                    "warning",
                    "429 %s, пауза %ss (попытка %s/%s)",
                    label,
                    delay,
                    attempt + 1,
                    len(BACKOFF_429) + 1,
                )
                time.sleep(delay)

            try:
                response = self.session.get(
                    url,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
            except requests.RequestException as e:
                reason = str(e)
                if self.stats is not None:
                    self.stats.http_failed += 1
                self.record_failure_fn("http", url, reason)
                self.log_fn("error", "HTTP %s: %s", label, reason)
                return None

            if response.status_code == 429:
                if attempt < len(BACKOFF_429):
                    continue
                reason = "429, исчерпаны повторы"
                if self.stats is not None:
                    self.stats.http_failed += 1
                self.record_failure_fn("http", url, reason)
                self.log_fn("error", "%s %s", reason, label)
                return None

            try:
                response.raise_for_status()
            except requests.HTTPError as e:
                reason = str(e)
                if self.stats is not None:
                    self.stats.http_failed += 1
                self.record_failure_fn("http", url, reason)
                self.log_fn("error", "HTTP %s: %s", label, reason)
                return None

            if self.stats is not None:
                self.stats.http_ok += 1
            self.log_fn("debug", "HTTP OK %s", label)
            return response

        return None
