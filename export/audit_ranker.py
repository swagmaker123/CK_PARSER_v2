import logging
import os
from pathlib import Path

import pandas as pd

from llm.audit_ranker import (
    _checkpoint_every,
    prepare_df_for_ranking,
    rank_top_by_ck,
    score_and_dedupe_news,
)

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


def _write_excel_atomic(excel_path: Path, sheets: dict, *, drop_internal: bool) -> None:
    """Пишет Excel через временный файл, чтобы не портить оригинал при обрыве."""
    excel_path = Path(excel_path)
    tmp_path = excel_path.with_suffix(excel_path.suffix + ".tmp")
    try:
        with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
            for sheet_name, df in sheets.items():
                out = _drop_internal_columns(df) if drop_internal else df
                out.to_excel(writer, sheet_name=sheet_name, index=False)
        os.replace(tmp_path, excel_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def audit_rank_excel(excel_path, ck_filter=None):
    """
    Ежедневный enrich: LLM scoring + semantic dedupe.

    Второй проход (top ranking) — отдельно через rank_top_excel / --rank-only.
    Во время scoring сохраняет checkpoint (с `_audit_*`).
    В финальном файле служебные `_audit_*` удаляются; остаются llm_score / llm_summary.
    """
    excel_path = Path(excel_path)

    if not excel_path.exists():
        raise FileNotFoundError(f"Файл не найден: {excel_path}")

    logger.info("LLM enrich (score + dedupe): %s", excel_path.name)
    every = _checkpoint_every()
    logger.info(
        "Checkpoint каждые %s строк (ENRICH_CHECKPOINT_EVERY), resume по _audit_ck_id",
        every,
    )

    sheets = pd.read_excel(excel_path, sheet_name=None)
    enriched = {}

    for sheet_name, df in sheets.items():
        logger.info("  Лист «%s»: %d строк", sheet_name, len(df))

        if df.empty:
            enriched[sheet_name] = df
            continue

        def on_checkpoint(current_df, *, _sheet=sheet_name):
            snapshot = {}
            for name, original in sheets.items():
                if name in enriched:
                    snapshot[name] = enriched[name]
                elif name == _sheet:
                    snapshot[name] = current_df
                else:
                    snapshot[name] = original
            _write_excel_atomic(excel_path, snapshot, drop_internal=False)
            scored = int(
                current_df["_audit_ck_id"].fillna("").astype(str).str.strip().ne("").sum()
            ) if "_audit_ck_id" in current_df.columns else 0
            msg = (
                f"Checkpoint: {excel_path.name} | лист «{_sheet}» "
                f"оценено {scored}/{len(current_df)}"
            )
            logger.info(msg)
            print(msg)

        enriched_df = score_and_dedupe_news(
            df,
            ck_filter=ck_filter,
            checkpoint_every=every,
            on_checkpoint=on_checkpoint,
        )
        enriched[sheet_name] = enriched_df
        logger.info("  → score+dedupe готово: %d строк", len(enriched_df))

    _write_excel_atomic(excel_path, enriched, drop_internal=True)
    logger.info("LLM enrich завершен: %s", excel_path)
    return excel_path


def rank_top_excel(excel_path, top_n=10, reserve_n=5, ck_filter=None):
    """
    Второй проход: top_n + reserve_n по каждому ЦК.

    Ожидает Excel после --enrich (колонка llm_score).
    Пишет top_rank / is_top_news.
    """
    excel_path = Path(excel_path)

    if not excel_path.exists():
        raise FileNotFoundError(f"Файл не найден: {excel_path}")

    logger.info(
        "LLM top ranking: %s (top_n=%s, reserve_n=%s)",
        excel_path.name,
        top_n,
        reserve_n,
    )

    sheets = pd.read_excel(excel_path, sheet_name=None)
    ranked = {}

    for sheet_name, df in sheets.items():
        logger.info("  Лист «%s»: %d строк", sheet_name, len(df))

        if df.empty:
            ranked[sheet_name] = df
            continue

        prepared = prepare_df_for_ranking(df, ck_filter=ck_filter)
        ranked_df = rank_top_by_ck(
            prepared,
            top_n=top_n,
            reserve_n=reserve_n,
            ck_filter=ck_filter,
        )
        ranked[sheet_name] = ranked_df

        top_count = (
            int(ranked_df["is_top_news"].fillna(False).astype(bool).sum())
            if "is_top_news" in ranked_df.columns
            else 0
        )
        logger.info("  → %d top-новостей помечено", top_count)
        print(f"Лист «{sheet_name}»: top-новостей = {top_count}")

    _write_excel_atomic(excel_path, ranked, drop_internal=True)
    logger.info("LLM top ranking завершен: %s", excel_path)
    return excel_path
