"""
Семантическая дедупликация между 1-м и 2-м этапом LLM enrich.

Embeddings только через Cloud.ru Foundation Models.
"""

from dedupe.embeddings import (
    describe_unavailable_reason,
    get_embedding_backend,
    is_dedupe_available,
)
from dedupe.semantic import dedupe_scored_rows_by_ck

__all__ = [
    "dedupe_scored_rows_by_ck",
    "describe_unavailable_reason",
    "get_embedding_backend",
    "is_dedupe_available",
]
