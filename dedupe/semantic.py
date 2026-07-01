from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from dedupe import config
from dedupe.embeddings import describe_unavailable_reason, get_embedding_backend, is_dedupe_available

logger = logging.getLogger(__name__)


@dataclass
class DuplicateGroup:
    keep_index: int
    duplicate_indices: list[int]


class UnionFind:
    def __init__(self, values: Iterable[int]):
        self.parent = {value: value for value in values}

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left

    def groups(self) -> list[list[int]]:
        grouped: dict[int, list[int]] = {}
        for value in self.parent:
            grouped.setdefault(self.find(value), []).append(value)
        return list(grouped.values())


def normalize_text(value) -> str:
    return " ".join(str(value or "").split())


def build_embedding_text(row: pd.Series) -> str:
    title = normalize_text(row.get(config.TITLE_COLUMN, ""))
    summary = normalize_text(row.get(config.SUMMARY_COLUMN, ""))

    if not summary:
        full_text = normalize_text(row.get(config.FULL_TEXT_COLUMN, ""))
        summary = full_text[: config.FULL_TEXT_FALLBACK_CHARS]

    return f"Заголовок: {title}\nКраткое содержание: {summary}".strip()


def row_llm_score(df: pd.DataFrame, index: int) -> int:
    score = pd.to_numeric(df.at[index, config.SCORE_COLUMN], errors="coerce")
    if pd.isna(score):
        return 0
    return int(score)


def build_duplicate_groups(
    df: pd.DataFrame,
    indices: list[int],
    similarities: np.ndarray,
) -> list[DuplicateGroup]:
    uf = UnionFind(indices)

    for i, left_index in enumerate(indices):
        for j in range(i + 1, len(indices)):
            right_index = indices[j]
            if float(similarities[i, j]) >= config.SIMILARITY_THRESHOLD:
                uf.union(left_index, right_index)

    duplicate_groups = []

    for group_indices in uf.groups():
        if len(group_indices) < 2:
            continue

        keep_index = max(group_indices, key=lambda idx: row_llm_score(df, idx))
        duplicate_indices = [
            idx for idx in sorted(group_indices) if idx != keep_index
        ]
        duplicate_groups.append(
            DuplicateGroup(
                keep_index=keep_index,
                duplicate_indices=duplicate_indices,
            )
        )

    return duplicate_groups


def find_rows_to_drop(
    df: pd.DataFrame,
    indices: list[int],
    backend,
) -> list[int]:
    if len(indices) < 2:
        return []

    texts = [build_embedding_text(df.loc[index]) for index in indices]
    embeddings = backend.encode(texts)
    similarities = np.matmul(embeddings, embeddings.T)
    duplicate_groups = build_duplicate_groups(df, indices, similarities)

    rows_to_drop = []
    for duplicate_group in duplicate_groups:
        keep_score = row_llm_score(df, duplicate_group.keep_index)
        keep_title = str(df.at[duplicate_group.keep_index, config.TITLE_COLUMN])[:70]

        for duplicate_index in duplicate_group.duplicate_indices:
            drop_score = row_llm_score(df, duplicate_index)
            drop_title = str(df.at[duplicate_index, config.TITLE_COLUMN])[:70]
            logger.info(
                "  dedupe: удалена score=%s «%s» → оставлена score=%s «%s»",
                drop_score,
                drop_title,
                keep_score,
                keep_title,
            )
            rows_to_drop.append(duplicate_index)

    return rows_to_drop


def dedupe_scored_rows_by_ck(
    df: pd.DataFrame,
    ck_filter=None,
    normalize_ck_filter_fn=None,
) -> pd.DataFrame:
    """
    После первого LLM-прохода удаляет семантические дубли среди всех строк
    каждого ЦК. Порог score / is_candidate здесь не используются.

    В каждой группе дублей остаётся строка с максимальным llm_score.
    """
    if not is_dedupe_available():
        if config.DEDUPE_ENABLED:
            logger.warning(
                "Semantic dedupe пропущен: %s",
                describe_unavailable_reason(),
            )
        else:
            logger.info("Semantic dedupe отключён (DEDUPE_ENABLED=false)")
        return df

    if normalize_ck_filter_fn is None:
        raise ValueError("normalize_ck_filter_fn is required")

    result = df.copy()
    allowed_ck_id = normalize_ck_filter_fn(ck_filter)
    backend = get_embedding_backend()
    rows_to_drop: list[int] = []

    ck_ids = sorted(
        ck_id
        for ck_id in result["_audit_ck_id"].fillna("").astype(str).unique()
        if ck_id and (allowed_ck_id is None or ck_id == allowed_ck_id)
    )

    for ck_id in ck_ids:
        ck_indices = result.index[
            result["_audit_ck_id"].astype(str).eq(ck_id)
        ].tolist()

        if len(ck_indices) < 2:
            continue

        dropped_for_ck = find_rows_to_drop(result, ck_indices, backend)
        if dropped_for_ck:
            logger.info(
                "ЦК %s: semantic dedupe удалит %s строк из %s",
                ck_id,
                len(dropped_for_ck),
                len(ck_indices),
            )
            rows_to_drop.extend(dropped_for_ck)

    if not rows_to_drop:
        logger.info("Semantic dedupe: дублей не найдено")
        return result

    unique_drop = sorted(set(rows_to_drop))
    logger.info("Semantic dedupe завершён: удалено строк=%s", len(unique_drop))
    return result.drop(index=unique_drop)
