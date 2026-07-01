import logging

from llm.config import TOP_N
from export.audit_ranker import audit_rank_excel

logger = logging.getLogger(__name__)


def enrich_excel(excel_path, top_n=TOP_N, reserve_n=5, ck_filter=None):
    """
    Основное LLM-обогащение проекта: двухэтапный audit ranking по каждому ЦК.

    Итоговые пользовательские колонки:
    - llm_summary: краткая суть новости из первого прохода
    - llm_score: оценка релевантности для аудиторского мониторинга ЦК
    - top_rank: место в итоговом top_n + reserve_n по своему ЦК
    - is_top_news: входит ли новость в основной top_n по своему ЦК
    """
    logger.info("LLM audit ranking: %s", excel_path)
    return audit_rank_excel(
        excel_path,
        top_n=top_n,
        reserve_n=reserve_n,
        ck_filter=ck_filter,
    )
