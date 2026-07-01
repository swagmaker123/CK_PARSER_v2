from __future__ import annotations

import logging
import os
from typing import Protocol

import numpy as np
import requests

from dedupe import config

logger = logging.getLogger(__name__)

_backend = None


class EmbeddingBackend(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray:
        ...


def _l2_normalize(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    return embeddings / norms


def _cloud_api_key() -> str:
    return str(os.getenv(config.EMBEDDING_API_KEY_ENV, "") or "").strip()


def _local_deps_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


def _cloud_available() -> bool:
    return bool(config.EMBEDDING_MODEL and _cloud_api_key())


def _local_available() -> bool:
    return config.EMBEDDING_MODEL_PATH.exists() and _local_deps_available()


def resolve_backend_kind() -> str | None:
    backend = config.DEDUPE_BACKEND

    if backend == "cloud":
        return "cloud" if _cloud_available() else None
    if backend == "local":
        return "local" if _local_available() else None
    if backend == "auto":
        if _cloud_available():
            return "cloud"
        if _local_available():
            return "local"
        return None

    logger.warning("Неизвестный DEDUPE_BACKEND=%s, используем auto", backend)
    if _cloud_available():
        return "cloud"
    if _local_available():
        return "local"
    return None


def is_dedupe_available() -> bool:
    if not config.DEDUPE_ENABLED:
        return False
    return resolve_backend_kind() is not None


class CloudEmbeddingBackend:
    def __init__(self):
        if not _cloud_available():
            raise RuntimeError(
                "Cloud embeddings недоступны: задайте EMBEDDING_MODEL и "
                f"{config.EMBEDDING_API_KEY_ENV}"
            )

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


class LocalEmbeddingBackend:
    def __init__(self):
        if not _local_available():
            raise RuntimeError(
                "Local dedupe недоступен: нет модели или sentence-transformers"
            )

        from sentence_transformers import SentenceTransformer

        logger.info("Загрузка локальной embedding-модели: %s", config.EMBEDDING_MODEL_PATH)
        self._model = SentenceTransformer(
            str(config.EMBEDDING_MODEL_PATH),
            device=config.EMBEDDING_DEVICE,
        )

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)

        embeddings = self._model.encode(
            texts,
            batch_size=config.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(embeddings, dtype=np.float32)


def get_embedding_backend() -> EmbeddingBackend:
    global _backend
    if _backend is not None:
        return _backend

    kind = resolve_backend_kind()
    if kind == "cloud":
        logger.info(
            "Semantic dedupe: cloud embeddings, model=%s",
            config.EMBEDDING_MODEL,
        )
        _backend = CloudEmbeddingBackend()
    elif kind == "local":
        _backend = LocalEmbeddingBackend()
    else:
        raise RuntimeError("Embedding backend недоступен")

    return _backend


def describe_unavailable_reason() -> str:
    if not config.DEDUPE_ENABLED:
        return "DEDUPE_ENABLED=false"

    kind = config.DEDUPE_BACKEND
    if kind == "cloud":
        if not config.EMBEDDING_MODEL:
            return "не задан EMBEDDING_MODEL"
        if not _cloud_api_key():
            return f"не задан {config.EMBEDDING_API_KEY_ENV}"
        return "cloud backend недоступен"

    if kind == "local":
        if not config.EMBEDDING_MODEL_PATH.exists():
            return f"локальная модель не найдена ({config.EMBEDDING_MODEL_PATH})"
        if not _local_deps_available():
            return "установите sentence-transformers (pip install sentence-transformers)"
        return "local backend недоступен"

    parts = []
    if not _cloud_available():
        parts.append(
            "cloud: нужны EMBEDDING_MODEL и "
            f"{config.EMBEDDING_API_KEY_ENV}"
        )
    if not _local_available():
        if not config.EMBEDDING_MODEL_PATH.exists():
            parts.append(
                f"local: модель не найдена ({config.EMBEDDING_MODEL_PATH})"
            )
        else:
            parts.append("local: нужен sentence-transformers")
    return "; ".join(parts) if parts else "backend недоступен"
