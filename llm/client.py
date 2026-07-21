import os
import json
import logging
import re
import time
import threading

import requests

from llm.config import (
    LLM_API_URL,
    LLM_MODEL,
    LLM_FALLBACK_MODELS,
    LLM_REQUEST_TIMEOUT,
    LLM_FAIL_THRESHOLD,
    TEMPERATURE,
    MAX_TOKENS,
)

logger = logging.getLogger(__name__)

# ─── Fallback state (thread-safe) ─────────────────────────────────────────────

_fail_lock = threading.Lock()
_consecutive_failures: int = 0
_active_model: str | None = None  # None = auto (try primary first)
_last_primary_retry: float = 0.0
_PRIMARY_RETRY_INTERVAL = 300  # каждые 5 мин пробуем primary снова


def get_active_model() -> str:
    """Какая модель сейчас активна (для логирования/диагностики)."""
    with _fail_lock:
        return _active_model or LLM_MODEL


def _should_skip_primary() -> bool:
    """True если primary модель пока не стоит пробовать."""
    with _fail_lock:
        if _consecutive_failures < LLM_FAIL_THRESHOLD:
            return False
        # Прошло ли достаточно времени с последней попытки primary?
        if time.time() - _last_primary_retry < _PRIMARY_RETRY_INTERVAL:
            return True
        # Пора попробовать primary снова
        _last_primary_retry = time.time()
        logger.info(
            "Пробуем вернуть primary модель %s после %s ошибок",
            LLM_MODEL,
            _consecutive_failures,
        )
        return False


def _record_success(model: str) -> None:
    with _fail_lock:
        global _active_model
        if model == LLM_MODEL:
            _consecutive_failures = 0
            if _active_model is not None:
                logger.info("Primary модель %s восстановлена", LLM_MODEL)
                _active_model = None
        else:
            _active_model = model


def _record_failure(model: str) -> None:
    with _fail_lock:
        global _active_model
        if model == LLM_MODEL:
            _consecutive_failures += 1
            if _consecutive_failures >= LLM_FAIL_THRESHOLD:
                fallback = LLM_FALLBACK_MODELS[0] if LLM_FALLBACK_MODELS else "нет"
                logger.warning(
                    "Primary модель %s: %s ошибок подряд → переключаемся на fallback (%s)",
                    LLM_MODEL,
                    _consecutive_failures,
                    fallback,
                )
                _active_model = (
                    LLM_FALLBACK_MODELS[0] if LLM_FALLBACK_MODELS else None
                )


def _model_queue() -> list[tuple[str, int]]:
    """
    Возвращает очередь моделей для попыток: (model_name, timeout_sec).
    Primary идёт первым, если неShould skip.
    """
    primary_timeout = LLM_REQUEST_TIMEOUT
    fallback_timeout = int(LLM_REQUEST_TIMEOUT * 1.5)

    queue: list[tuple[str, int]] = []

    if not _should_skip_primary():
        queue.append((LLM_MODEL, primary_timeout))

    for fm in LLM_FALLBACK_MODELS:
        queue.append((fm, fallback_timeout))

    # Если primary пропущен и fallback пуст — всё равно пробуем primary
    if not queue:
        queue.append((LLM_MODEL, primary_timeout))

    return queue


# ─── JSON extraction (без изменений) ──────────────────────────────────────────

def extract_json_from_response(content: str) -> dict:
    """
    Извлекает JSON из ответа LLM.

    Обрабатывает случаи:
    1. Чистый JSON: '{"summary": "...", "score": 50}'
    2. JSON в markdown-блоке: ```json ... ```
    3. JSON, встроенный в reasoning-текст: '... текст ... {"summary": "...", "score": 50}'
    4. JSON после </think>-тега (Qwen3.6 thinking format)
    """
    if content is None:
        raise ValueError("LLM вернул None в content")

    text = str(content).strip()

    # Убираем </think> теги (Qwen3.6 формат)
    think_end = text.rfind("</think>")
    if think_end >= 0:
        text = text[think_end + len("</think>"):].strip()

    # Убираем markdown-обёртку
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    # Пробуем распарсить как чистый JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Универсальный фолбэк: ищем первый сбалансированный JSON-объект.
    start = text.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        escape = False

        for pos in range(start, len(text)):
            char = text[pos]

            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:pos + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    # Ищем последний JSON-объект с ключом "summary" в тексте
    pattern = r'\{[^{}]*"summary"\s*:\s*"[^"]*"[^{}]*"score"\s*:\s*\d+[^{}]*\}'
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        for match in reversed(matches):
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

    # Фоллбэк: ищем любой JSON-объект с "summary"
    pattern2 = r'\{[^{}]*"summary"[^{}]*\}'
    matches2 = re.findall(pattern2, text, re.DOTALL)
    if matches2:
        for match in reversed(matches2):
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

    # Фоллбэк: GigaChat иногда не экранирует кавычки внутри значений.
    summary_match = re.search(r'"summary"\s*:\s*"(.+?)"\s*,\s*"score"', text, re.DOTALL)
    score_match = re.search(r'"score"\s*:\s*(\d+)', text)
    if summary_match and score_match:
        raw_summary = summary_match.group(1).strip()
        raw_summary = raw_summary.replace('\n', ' ').replace('\r', '')
        score = int(score_match.group(1))
        logger.warning(
            "JSON невалиден (неэкранированные кавычки?), извлечено через regex: score=%d",
            score,
        )
        return {"summary": raw_summary, "score": score}

    raise json.JSONDecodeError(
        f"Не удалось извлечь JSON из ответа LLM. Первые 500 символов: {text[:500]}",
        text, 0,
    )


# ─── LLM call with fallback ───────────────────────────────────────────────────

def _do_single_request(
    prompt: str,
    model: str,
    timeout: int,
    api_key: str,
) -> dict:
    """Один LLM-запрос к конкретной модели. Возвращает parsed JSON."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    logger.debug("LLM запрос: model=%s, timeout=%ss", model, timeout)

    response = requests.post(
        LLM_API_URL,
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()

    data = response.json()
    message = data["choices"][0]["message"]
    content = message.get("content")

    if content is None:
        reasoning = message.get("reasoning")
        if reasoning:
            content = reasoning
        else:
            raise ValueError(
                "LLM вернул пустой ответ (content=None, reasoning=None)"
            )

    return extract_json_from_response(content)


def call_llm_json(prompt: str) -> dict:
    """
    Отправляет промпт в LLM API и возвращает JSON-ответ.

    Автоматический fallback:
    - Если primary модель таймаутит или падает — пробуем fallback-модели.
    - После LLM_FAIL_THRESHOLD ошибок подряд primary пропускается.
    - Каждые 5 минут primary пробуется снова (авто-recovery).

    Ретраи на 429/502/503/504 и сетевые сбои (LLM_MAX_RETRIES, по умолчанию 3).
    """
    api_key = os.getenv("FOUNDATION_MODELS_API_KEY")
    if not api_key:
        raise ValueError(
            "Не задан FOUNDATION_MODELS_API_KEY. "
            "Экспортируйте переменную окружения или добавьте её в .env"
        )

    max_retries = _env_int("LLM_MAX_RETRIES", 3)
    backoff = _env_float("LLM_RETRY_BACKOFF", 2.0)

    # Очередь моделей: primary (если активна) → fallback'и
    model_queue = _model_queue()

    last_error: Exception | None = None

    for model_idx, (model, model_timeout) in enumerate(model_queue):
        is_primary = model == LLM_MODEL
        is_last_model = model_idx == len(model_queue) - 1

        for attempt in range(max_retries + 1):
            try:
                result = _do_single_request(prompt, model, model_timeout, api_key)
                _record_success(model)

                if not is_primary:
                    logger.info(
                        "LLM ответ от fallback модели %s (score=%s)",
                        model,
                        result.get("score", "?"),
                    )

                return result

            except requests.exceptions.Timeout as e:
                last_error = e
                logger.warning(
                    "LLM %s: таймаут (%ss), попытка %s/%s",
                    model,
                    model_timeout,
                    attempt + 1,
                    max_retries + 1,
                )
                if attempt < max_retries:
                    time.sleep(backoff * (2 ** attempt))
                # Переходим к следующей модели

            except requests.exceptions.ConnectionError as e:
                last_error = e
                logger.warning(
                    "LLM %s: сетевая ошибка (%s), попытка %s/%s",
                    model,
                    e,
                    attempt + 1,
                    max_retries + 1,
                )
                if attempt < max_retries:
                    time.sleep(backoff * (2 ** attempt))

            except requests.exceptions.HTTPError as e:
                last_error = e
                status = getattr(e.response, "status_code", None)
                if status in _RETRYABLE_STATUS and attempt < max_retries:
                    wait = backoff * (2 ** attempt)
                    logger.warning(
                        "LLM %s: HTTP %s, повтор %s/%s через %.1fs",
                        model,
                        status,
                        attempt + 1,
                        max_retries,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                # Неретраимая ошибка — следующая модель
                logger.warning(
                    "LLM %s: HTTP %s → следующая модель",
                    model,
                    status,
                )
                break

            except Exception as e:
                last_error = e
                logger.warning(
                    "LLM %s: ошибка %s → следующая модель",
                    model,
                    e,
                )
                break

        # Primary не отработал — фиксируем failure
        if is_primary:
            _record_failure(model)

        if not is_last_model:
            next_model = model_queue[model_idx + 1][0]
            logger.info(
                "Переключаемся на следующую модель: %s",
                next_model,
            )

    raise RuntimeError(
        f"LLM запрос не удалён ни для одной модели ({', '.join(m for m, _ in model_queue)}). "
        f"Последняя ошибка: {last_error}"
    ) from last_error


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


_RETRYABLE_STATUS = {429, 502, 503, 504}
