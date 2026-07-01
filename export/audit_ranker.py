import logging
from pathlib import Path

import pandas as pd

from llm.audit_ranker import audit_rank_news

logger = logging.getLogger(__name__)


def _drop_internal_columns(df):
    columns_to_drop = [
        column
        for column in df.columns
        if column.startswith("_audit_") or column.startswith("audit_")
    ]
    if columns_to_drop:
        return df.drop(columns=columns_to_drop)
    return df


def audit_rank_excel(excel_path, top_n=10, reserve_n=5, ck_filter=None):
    """
    Читает готовый Excel, выполняет двухпроходное LLM-ранжирование по каждому ЦК
    и перезаписывает файл.

    Первый проход оценивает каждую новость своим профилем ЦК.
    Второй проход выбирает top_n + reserve_n кандидатов отдельно по каждому ЦК.
    """
    excel_path = Path(excel_path)

    if not excel_path.exists():
        raise FileNotFoundError(f"Файл не найден: {excel_path}")

    logger.info("Audit ranking: %s", excel_path.name)

    sheets = pd.read_excel(excel_path, sheet_name=None)
    ranked = {}

    for sheet_name, df in sheets.items():
        logger.info("  Лист «%s»: %d строк", sheet_name, len(df))

        if df.empty:
            ranked[sheet_name] = _drop_internal_columns(df)
            continue

        ranked_df = audit_rank_news(
            df,
            top_n=top_n,
            reserve_n=reserve_n,
            ck_filter=ck_filter,
        )
        ranked[sheet_name] = _drop_internal_columns(ranked_df)

        top_count = (
            int(ranked_df["is_top_news"].fillna(False).astype(bool).sum())
            if "is_top_news" in ranked_df.columns
            else 0
        )
        logger.info("  → %d top-новостей помечено", top_count)

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        for sheet_name, df in ranked.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    logger.info("Audit ranking завершен: %s", excel_path)
    return excel_path
