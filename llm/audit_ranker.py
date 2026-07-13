import logging
import os

import pandas as pd

from llm.client import call_llm_json
from llm.ranking_prompts import get_profile, normalize_ck_id
from llm.ranking_prompts.base import build_ranking_prompt, build_scoring_prompt

logger = logging.getLogger(__name__)

SCORING_COLUMNS = [
    "_audit_ck_id",
    "llm_score",
    "_audit_is_candidate",
    "_audit_topic",
    "llm_summary",
    "_audit_reason",
]

RANKING_COLUMNS = [
    "top_rank",
    "is_top_news",
]

MAX_RANKING_CANDIDATES = 30
DEFAULT_CHECKPOINT_EVERY = 10
LLM_ERROR_REASON_PREFIX = "Ошибка LLM scoring:"


def _checkpoint_every() -> int:
    raw = os.getenv("ENRICH_CHECKPOINT_EVERY", "").strip()
    if not raw:
        return DEFAULT_CHECKPOINT_EVERY
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_CHECKPOINT_EVERY


def _is_llm_error_row(row) -> bool:
    """Строка упала на LLM (503 и т.п.) — при resume переобработаем."""
    reason = row.get("_audit_reason")
    if reason is None:
        return False
    try:
        if pd.isna(reason):
            return False
    except (TypeError, ValueError):
        pass
    return str(reason).strip().startswith(LLM_ERROR_REASON_PREFIX)


def _row_already_scored(row) -> bool:
    """Строка уже успешно прошла 1-й проход (есть _audit_ck_id, без LLM-ошибки)."""
    if _is_llm_error_row(row):
        return False

    value = row.get("_audit_ck_id")
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return bool(text) and text.lower() not in ("nan", "none")


def _ensure_columns(df, columns, default=None):
    for column in columns:
        if column not in df.columns:
            df[column] = None   # создаёт object dtype, не StringDtype
        else:
            # Приводим к object, чтобы избежать StringDtype/BoolDtype
            # при записи mix значений (int/str/bool)
            if df[column].dtype != object:
                df[column] = df[column].astype(object)
    return df


def _as_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in ("1", "true", "yes", "да")


def _as_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clean_score(value):
    return max(0, min(100, _as_int(value, default=0)))


def _candidate_payload(row_id, row):
    return {
        "row_id": int(row_id),
        "date": str(row.get("Дата новости", "") or ""),
        "source": str(row.get("Источник", "") or ""),
        "title": str(row.get("Заголовок статьи", "") or ""),
        "keywords": str(row.get("Ключевые слова", "") or ""),
        "score": _clean_score(row.get("llm_score", 0)),
        "topic": str(row.get("_audit_topic", "") or ""),
        "short_summary": str(row.get("llm_summary", "") or ""),
        "reason": str(row.get("_audit_reason", "") or ""),
    }


def _normalize_ck_filter(ck_filter):
    if ck_filter is None:
        return None

    value = str(ck_filter or "").strip()
    if not value or value == "all":
        return None

    return normalize_ck_id(value)


def score_news_by_ck(
    final_df,
    ck_filter=None,
    checkpoint_every=None,
    on_checkpoint=None,
):
    """
    Первый проход: каждая строка оценивается своим промптом ЦК.

    Уже оценённые строки (есть `_audit_ck_id` из checkpoint) пропускаются —
    можно продолжить после обрыва тем же `--enrich-only` по тому же Excel.

    `on_checkpoint(df)` вызывается каждые `checkpoint_every` новых оценок
    и в конце скоринга (если был прогресс).
    """
    df = final_df.copy()
    _ensure_columns(df, SCORING_COLUMNS)
    allowed_ck_id = _normalize_ck_filter(ck_filter)
    every = (
        _checkpoint_every()
        if checkpoint_every is None
        else max(1, int(checkpoint_every))
    )

    total = len(df)
    processed = 0
    skipped = 0
    resumed = 0
    errors = 0
    since_checkpoint = 0

    def _maybe_checkpoint(force: bool = False) -> None:
        nonlocal since_checkpoint
        if on_checkpoint is None:
            return
        if since_checkpoint == 0:
            return
        if not force and since_checkpoint < every:
            return
        on_checkpoint(df)
        since_checkpoint = 0

    for idx, row in df.iterrows():
        if _row_already_scored(row):
            resumed += 1
            continue

        ck_name = row.get("Наименование ЦК", "")
        profile = get_profile(ck_name)

        if profile is None:
            logger.warning("Строка %s: неизвестный ЦК: %s", idx, ck_name)
            df.at[idx, "_audit_ck_id"] = normalize_ck_id(ck_name)
            df.at[idx, "llm_score"] = 0
            df.at[idx, "_audit_is_candidate"] = "0"
            df.at[idx, "_audit_topic"] = "not_relevant"
            df.at[idx, "_audit_reason"] = f"Не найден профиль ранжирования для ЦК: {ck_name}"
            skipped += 1
            since_checkpoint += 1
            _maybe_checkpoint()
            continue

        if allowed_ck_id is not None and profile.ck_id != allowed_ck_id:
            skipped += 1
            continue

        try:
            prompt = build_scoring_prompt(profile, row)
            result = call_llm_json(prompt)

            score = _clean_score(result.get("score", 0))
            is_candidate = _as_bool(result.get("is_candidate", score >= 60))
            topic = str(result.get("topic", "not_relevant") or "not_relevant")
            summary = str(
                result.get("summary") or result.get("short_summary") or ""
            ).strip()
            reason = str(result.get("reason", "") or "").strip()

            df.at[idx, "_audit_ck_id"] = profile.ck_id
            df.at[idx, "llm_score"] = score
            df.at[idx, "_audit_is_candidate"] = "1" if is_candidate else "0"
            df.at[idx, "_audit_topic"] = topic
            df.at[idx, "llm_summary"] = summary
            df.at[idx, "_audit_reason"] = reason

            processed += 1
            since_checkpoint += 1
            logger.info(
                "  [%s/%s] %s score=%s candidate=%s | %s",
                resumed + processed + skipped,
                total,
                profile.ck_title,
                score,
                is_candidate,
                str(row.get("Заголовок статьи", ""))[:70],
            )
            _maybe_checkpoint()
        except Exception as e:
            errors += 1
            logger.error("Ошибка audit scoring строки %s: %s", idx, e)
            df.at[idx, "_audit_ck_id"] = profile.ck_id
            df.at[idx, "llm_score"] = 0
            df.at[idx, "_audit_is_candidate"] = "0"
            df.at[idx, "_audit_topic"] = "not_relevant"
            df.at[idx, "_audit_reason"] = f"{LLM_ERROR_REASON_PREFIX} {e}"
            since_checkpoint += 1
            _maybe_checkpoint()

    if since_checkpoint:
        _maybe_checkpoint(force=True)

    if resumed:
        logger.info(
            "score_news_by_ck: продолжение с checkpoint, уже оценено строк=%s",
            resumed,
        )
    logger.info(
        "score_news_by_ck завершено: обработано=%s, из checkpoint=%s, "
        "пропущено=%s, ошибок=%s",
        processed,
        resumed,
        skipped,
        errors,
    )
    return df


def _clear_ranking_for_mask(df, mask):
    for column in RANKING_COLUMNS:
        if column == "is_top_news":
            df.loc[mask, column] = "0"
        else:
            df.loc[mask, column] = ""


def rank_top_by_ck(final_df, top_n=10, reserve_n=5, ck_filter=None):
    """
    Второй проход: отдельно по каждому ЦК выбирается top_n + reserve_n
    кандидатов. В LLM уходит компактный список без полного текста статей.
    """
    df = final_df.copy()
    _ensure_columns(df, SCORING_COLUMNS)
    _ensure_columns(df, RANKING_COLUMNS)
    allowed_ck_id = _normalize_ck_filter(ck_filter)

    ck_ids = sorted(
        ck_id
        for ck_id in df["_audit_ck_id"].fillna("").astype(str).unique()
        if ck_id and (allowed_ck_id is None or ck_id == allowed_ck_id)
    )

    for ck_id in ck_ids:
        profile = get_profile(ck_id)
        if profile is None:
            logger.warning("Пропускаем ranking для неизвестного ЦК: %s", ck_id)
            continue

        ck_mask = df["_audit_ck_id"].astype(str).eq(ck_id)
        candidate_mask = ck_mask & df["_audit_is_candidate"].apply(_as_bool)
        candidates_df = df.loc[candidate_mask].copy()

        if candidates_df.empty:
            logger.info("ЦК %s: нет кандидатов для top ranking", profile.ck_title)
            _clear_ranking_for_mask(df, ck_mask)
            continue

        candidates_df["__score"] = candidates_df["llm_score"].apply(_clean_score)
        candidates_df = candidates_df.sort_values("__score", ascending=False)
        if len(candidates_df) > MAX_RANKING_CANDIDATES:
            logger.info(
                "ЦК %s: кандидатов %s, во второй проход берём top-%s по score",
                profile.ck_title,
                len(candidates_df),
                MAX_RANKING_CANDIDATES,
            )
            candidates_df = candidates_df.head(MAX_RANKING_CANDIDATES)
        candidates = [
            _candidate_payload(idx, row)
            for idx, row in candidates_df.iterrows()
        ]

        logger.info(
            "ЦК %s: отправляем во второй проход %s кандидатов",
            profile.ck_title,
            len(candidates),
        )

        prompt = build_ranking_prompt(
            profile,
            candidates,
            top_n=top_n,
            reserve_n=reserve_n,
        )
        result = call_llm_json(prompt)

        _clear_ranking_for_mask(df, ck_mask)

        for item in result.get("ranked_top15", []) or []:
            row_id = item.get("row_id")
            if row_id not in df.index:
                continue

            rank = _as_int(item.get("rank"), default=0)
            if rank <= 0:
                continue

            df.at[row_id, "top_rank"] = rank
            df.at[row_id, "is_top_news"] = "1" if rank <= top_n else "0"

    return df


def audit_rank_news(
    final_df,
    top_n=10,
    reserve_n=5,
    ck_filter=None,
    checkpoint_every=None,
    on_checkpoint=None,
):
    scored = score_news_by_ck(
        final_df,
        ck_filter=ck_filter,
        checkpoint_every=checkpoint_every,
        on_checkpoint=on_checkpoint,
    )

    from dedupe.semantic import dedupe_scored_rows_by_ck

    scored = dedupe_scored_rows_by_ck(
        scored,
        ck_filter=ck_filter,
        normalize_ck_filter_fn=_normalize_ck_filter,
    )
    if on_checkpoint is not None:
        on_checkpoint(scored)

    ranked = rank_top_by_ck(
        scored,
        top_n=top_n,
        reserve_n=reserve_n,
        ck_filter=ck_filter,
    )
    if on_checkpoint is not None:
        on_checkpoint(ranked)
    return ranked
