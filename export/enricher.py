import logging

from export.audit_ranker import audit_rank_excel, rank_top_excel
from llm.config import TOP_N

logger = logging.getLogger(__name__)


def enrich_excel(excel_path, top_n=TOP_N, reserve_n=5, ck_filter=None):
    """
    Ежедневное LLM-обогащение: scoring + semantic dedupe.

    Колонки:
    - llm_summary
    - llm_score

    Второй проход (top_rank / is_top_news) — отдельно: rank_excel / --rank-only.
    """
    logger.info("LLM enrich (score + dedupe): %s", excel_path)
    return audit_rank_excel(excel_path, ck_filter=ck_filter)


def rank_excel(excel_path, top_n=TOP_N, reserve_n=5, ck_filter=None):
    """
    Второй проход LLM: ранжирование top_n + reserve_n по каждому ЦК.

    Нужен Excel после enrich (llm_score). Результат: top_rank, is_top_news.
    """
    logger.info("LLM top ranking: %s", excel_path)
    return rank_top_excel(
        excel_path,
        top_n=top_n,
        reserve_n=reserve_n,
        ck_filter=ck_filter,
    )
