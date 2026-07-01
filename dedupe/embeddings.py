from __future__ import annotations

import logging
import os

import numpy as np
import requests

from dedupe import config

logger = logging.getLogger(__name__)

_backend = None


def _l2_normalize(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    return embeddings / norms


def _cloud_api_key() -> str:
    return str(os.getenv(config.EMBEDDING_API_KEY_ENV, "") or "").strip()


def is_dedupe_available() -> bool:
    if not config.DEDUPE_ENABLED:
        return False
    return bool(config.EMBEDDING_MODEL and _cloud_api_key())


class CloudEmbeddingBackend:
    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)

        api_key = _cloud_api_key()
        all_embeddings: list[list[float]] = []
        batch_size = max(1, config.EMBEDDING_BATCH_SIZE)

        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = requests.post(
                config.EMBEDDING_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.EMBEDDING_MODEL,
                    "input": batch,
                },
                timeout=config.EMBEDDING_TIMEOUT,
            )
            response.raise_for_status()

            payload = response.json()
            items = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
            if len(items) != len(batch):
                raise ValueError(
                    f"Embeddings API вернул {len(items)} векторов вместо {len(batch)}"
                )

            all_embeddings.extend(item["embedding"] for item in items)

        embeddings = np.asarray(all_embeddings, dtype=np.float32)
        return _l2_normalize(embeddings)


def get_embedding_backend() -> CloudEmbeddingBackend:
    global _backend
    if _backend is not None:
        return _backend

    if not is_dedupe_available():
        raise RuntimeError(describe_unavailable_reason())

    logger.info(
        "Semantic dedupe: cloud embeddings, model=%s",
        config.EMBEDDING_MODEL,
    )
    _backend = CloudEmbeddingBackend()
    return _backend


def describe_unavailable_reason() -> str:
    if not config.DEDUPE_ENABLED:
        return "DEDUPE_ENABLED=false"
    if not config.EMBEDDING_MODEL:
        return "не задан EMBEDDING_MODEL"
    if not _cloud_api_key():
        return f"не задан {config.EMBEDDING_API_KEY_ENV}"
    return "cloud embeddings недоступны"
