import os
import json
import logging
import re
import time

import requests

from llm.config import LLM_API_URL, LLM_MODEL, TEMPERATURE, MAX_TOKENS

logger = logging.getLogger(__name__)


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
    # Нужен для новых промптов, где JSON может содержать вложенные массивы.
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
    # (для случая, когда reasoning содержит JSON в конце)
    pattern = r'\{[^{}]*"summary"\s*:\s*"[^"]*"[^{}]*"score"\s*:\s*\d+[^{}]*\}'
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        for match in reversed(matches):
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

    # Фолбэк: ищем любой JSON-объект с "summary"
    pattern2 = r'\{[^{}]*"summary"[^{}]*\}'
    matches2 = re.findall(pattern2, text, re.DOTALL)
    if matches2:
        for match in reversed(matches2):
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

    # Фоллбэк: GigaChat иногда не экранирует кавычки внутри значений.
    # Пытаемся вытащить summary и score через regex.
    summary_match = re.search(r'"summary"\s*:\s*"(.+?)"\s*,\s*"score"', text, re.DOTALL)
    score_match = re.search(r'"score"\s*:\s*(\d+)', text)
    if summary_match and score_match:
        raw_summary = summary_match.group(1).strip()
        # Убираем лишние экранирования, если модель добавила \
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


def call_llm_json(prompt: str) -> dict:
    """
    Отправляет промпт в LLM API и возвращает произвольный JSON-ответ.
    Используется новыми сценариями, где структура ответа не ограничена
    summary/score.
    """
    api_key = os.getenv("FOUNDATION_MODELS_API_KEY")
    if not api_key:
        raise ValueError(
            "Не задан FOUNDATION_MODELS_API_KEY. "
            "Экспортируйте переменную окружения или добавьте её в .env"
        )

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }

    logger.debug("LLM запрос: model=%s, temperature=%s", LLM_MODEL, TEMPERATURE)

    response = requests.post(
        LLM_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=300,
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
            raise ValueError("LLM вернул пустой ответ (content=None, reasoning=None)")

    return extract_json_from_response(content)
