import logging
import os
from datetime import datetime

from common.paths import PROJECT_ROOT

LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")


class RunStats:
    def __init__(self):
        self.http_ok = 0
        self.http_failed = 0
        self.http_429_retries = 0
        self.archive_pages_failed = 0
        self.parse_failed = 0
        self.empty_title = 0
        self.filter_skipped = 0
        self.duplicate_skipped = 0
        self.failed_items = []

    def record_failure(self, kind, target, reason):
        self.failed_items.append(
            {
                "kind": kind,
                "target": target,
                "reason": reason,
            }
        )


def setup_run_logger(name="ck_parser"):
    os.makedirs(LOGS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(LOGS_DIR, f"run_{timestamp}.log")

    logger = logging.getLogger(f"{name}.{timestamp}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False

    return logger, log_file


def log_run_summary(logger, stats):
    logger.info("========== СВОДКА ОШИБОК ==========")
    logger.info("HTTP успешно: %s", stats.http_ok)
    logger.info("HTTP ошибок: %s", stats.http_failed)
    logger.info("HTTP 429 (повторы): %s", stats.http_429_retries)
    logger.info("Страниц архива не загружено: %s", stats.archive_pages_failed)
    logger.info("Ошибок разбора HTML: %s", stats.parse_failed)
    logger.info("Пустой заголовок: %s", stats.empty_title)
    logger.info("Дубликаты: %s", stats.duplicate_skipped)
    logger.info("Не прошли фильтр: %s", stats.filter_skipped)
    logger.info("Всего дропов с причиной: %s", len(stats.failed_items))

    if stats.failed_items:
        logger.info("---------- Детали дропов ----------")
        for item in stats.failed_items:
            logger.info(
                "[%s] %s — %s",
                item["kind"],
                item["target"],
                item["reason"],
            )
