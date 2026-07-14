from __future__ import annotations

import logging
import os
import time

import numpy as np
import requests

from dedupe import config

logger = logging.getLogger(__name__)

_backend = None
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.1, float(raw))
    except ValueError:
        return default


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
        max_retries = _env_int("EMBEDDING_MAX_RETRIES", 3)
        backoff = _env_float("EMBEDDING_RETRY_BACKOFF", 2.0)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            items = self._encode_batch(
                batch,
                headers=headers,
                max_retries=max_retries,
                backoff=backoff,
            )
            all_embeddings.extend(item["embedding"] for item in items)

        embeddings = np.asarray(all_embeddings, dtype=np.float32)
        return _l2_normalize(embeddings)

    def _encode_batch(
        self,
        batch: list[str],
        *,
        headers: dict,
        max_retries: int,
        backoff: float,
    ) -> list[dict]:
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    config.EMBEDDING_API_URL,
                    headers=headers,
                    json={
                        "model": config.EMBEDDING_MODEL,
                        "input": batch,
                    },
                    timeout=config.EMBEDDING_TIMEOUT,
                )
                if response.status_code in _RETRYABLE_STATUS and attempt < max_retries:
                    wait = backoff * (2 ** attempt)
                    logger.warning(
                        "Embeddings HTTP %s, повтор %s/%s через %.1fs",
                        response.status_code,
                        attempt + 1,
                        max_retries,
                        wait,
                    )
                    time.sleep(wait)
                    continue

                response.raise_for_status()

                payload = response.json()
                items = sorted(
                    payload.get("data", []),
                    key=lambda item: item.get("index", 0),
                )
                if len(items) != len(batch):
                    raise ValueError(
                        f"Embeddings API вернул {len(items)} векторов вместо {len(batch)}"
                    )
                return items

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_error = e
                if attempt >= max_retries:
                    break
                wait = backoff * (2 ** attempt)
                logger.warning(
                    "Embeddings сеть/таймаут (%s), повтор %s/%s через %.1fs",
                    e,
                    attempt + 1,
                    max_retries,
                    wait,
                )
                time.sleep(wait)
            except requests.exceptions.HTTPError as e:
                last_error = e
                status = getattr(e.response, "status_code", None)
                if status in _RETRYABLE_STATUS and attempt < max_retries:
                    wait = backoff * (2 ** attempt)
                    logger.warning(
                        "Embeddings HTTPError %s, повтор %s/%s через %.1fs",
                        status,
                        attempt + 1,
                        max_retries,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError(
            f"Embeddings запрос не удался после {max_retries + 1} попыток"
        ) from last_error


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
