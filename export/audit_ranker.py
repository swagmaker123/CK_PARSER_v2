import logging
import os
from pathlib import Path

import pandas as pd

from llm.audit_ranker import _checkpoint_every, audit_rank_news

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


def audit_rank_excel(excel_path, top_n=10, reserve_n=5, ck_filter=None):
    """
    Читает готовый Excel, выполняет двухпроходное LLM-ранжирование по каждому ЦК
    и перезаписывает файл.

    Во время 1-го прохода периодически сохраняет checkpoint (с `_audit_*`),
    чтобы можно было продолжить после обрыва тем же `--enrich-only`.
    В финальном файле служебные `_audit_*` колонки удаляются.
    """
    excel_path = Path(excel_path)

    if not excel_path.exists():
        raise FileNotFoundError(f"Файл не найден: {excel_path}")

    logger.info("Audit ranking: %s", excel_path.name)
    every = _checkpoint_every()
    logger.info(
        "Checkpoint каждые %s строк (ENRICH_CHECKPOINT_EVERY), resume по _audit_ck_id",
        every,
    )

    sheets = pd.read_excel(excel_path, sheet_name=None)
    ranked = {}

    for sheet_name, df in sheets.items():
        logger.info("  Лист «%s»: %d строк", sheet_name, len(df))

        if df.empty:
            ranked[sheet_name] = df
            continue

        def on_checkpoint(current_df, *, _sheet=sheet_name):
            snapshot = {}
            for name, original in sheets.items():
                if name in ranked:
                    snapshot[name] = ranked[name]
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

        ranked_df = audit_rank_news(
            df,
            top_n=top_n,
            reserve_n=reserve_n,
            ck_filter=ck_filter,
            checkpoint_every=every,
            on_checkpoint=on_checkpoint,
        )
        ranked[sheet_name] = ranked_df

        top_count = (
            int(ranked_df["is_top_news"].fillna(False).astype(bool).sum())
            if "is_top_news" in ranked_df.columns
            else 0
        )
        logger.info("  → %d top-новостей помечено", top_count)

    _write_excel_atomic(excel_path, ranked, drop_internal=True)
    logger.info("Audit ranking завершен: %s", excel_path)
    return excel_path
