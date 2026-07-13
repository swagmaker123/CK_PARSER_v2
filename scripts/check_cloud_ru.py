"""
Проверка подключения к Cloud.ru Foundation Models (LLM + embeddings).

Локальный env для теста:
  # вписать ключ в .env.example или .env:
  FOUNDATION_MODELS_API_KEY=...

Порядок загрузки: .env → .env.example → ~/.openclaw/.env

Запуск:
  python scripts/check_cloud_ru.py
  python scripts/check_cloud_ru.py --env .env
  python scripts/check_cloud_ru.py --llm-only
"""

from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import requests
from dotenv import load_dotenv

OPENCLAW_ENV_PATH = os.path.join(os.path.expanduser("~"), ".openclaw", ".env")
PROJECT_ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
PROJECT_ENV_EXAMPLE_PATH = os.path.join(PROJECT_ROOT, ".env.example")
API_KEY_ENV = "FOUNDATION_MODELS_API_KEY"


def load_env(env_file: str | None = None) -> list[str]:
    loaded: list[str] = []

    if env_file:
        path = env_file if os.path.isabs(env_file) else os.path.join(PROJECT_ROOT, env_file)
        if not os.path.isfile(path):
            raise SystemExit(f"Файл env не найден: {path}")
        load_dotenv(path, override=True)
        loaded.append(path)
        return loaded

    if os.path.isfile(PROJECT_ENV_PATH):
        load_dotenv(PROJECT_ENV_PATH, override=True)
        loaded.append(PROJECT_ENV_PATH)

    if os.path.isfile(PROJECT_ENV_EXAMPLE_PATH):
        load_dotenv(PROJECT_ENV_EXAMPLE_PATH, override=False)
        loaded.append(PROJECT_ENV_EXAMPLE_PATH)

    if os.path.isfile(OPENCLAW_ENV_PATH):
        load_dotenv(OPENCLAW_ENV_PATH, override=False)
        loaded.append(OPENCLAW_ENV_PATH)

    return loaded


def get_api_key() -> str:
    api_key = os.getenv(API_KEY_ENV, "").strip()
    if not api_key:
        raise SystemExit(
            f"Не задан {API_KEY_ENV}.\n\n"
            "Добавьте ключ в один из файлов:\n"
            f"  {PROJECT_ENV_EXAMPLE_PATH}\n"
            f"  {PROJECT_ENV_PATH}\n"
            f"  {OPENCLAW_ENV_PATH}\n\n"
            f"Пример строки:\n  {API_KEY_ENV}=ваш_ключ"
        )
    return api_key


def check_llm(api_key: str) -> None:
    llm_api_url = os.getenv(
        "LLM_API_URL",
        "https://foundation-models.api.cloud.ru/v1/chat/completions",
    )
    llm_model = os.getenv("LLM_MODEL", "ai-sage/GigaChat3-10B-A1.8B")
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))

    print(f"LLM: POST {llm_api_url}")
    print(f"     model={llm_model}")

    response = requests.post(
        llm_api_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": llm_model,
            "messages": [{"role": "user", "content": "Ответь одним словом: ок"}],
            "temperature": temperature,
            "max_tokens": min(32, max_tokens),
            "stream": False,
        },
        timeout=120,
    )

    if response.status_code != 200:
        print(f"     FAIL HTTP {response.status_code}")
        print(f"     {response.text[:500]}")
        raise SystemExit(1)

    data = response.json()
    message = data["choices"][0]["message"]
    content = message.get("content") or message.get("reasoning") or ""
    print(f"     OK  ответ: {str(content).strip()[:120]}")


def check_embeddings(api_key: str) -> None:
    model = os.getenv("EMBEDDING_MODEL", "").strip()
    if not model:
        print("Embeddings: SKIP (не задан EMBEDDING_MODEL в .env)")
        return

    embedding_api_url = os.getenv(
        "EMBEDDING_API_URL",
        "https://foundation-models.api.cloud.ru/v1/embeddings",
    )
    embedding_timeout = int(os.getenv("EMBEDDING_TIMEOUT", "120"))

    print(f"Embeddings: POST {embedding_api_url}")
    print(f"            model={model}")

    response = requests.post(
        embedding_api_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": ["тест подключения к embeddings"],
        },
        timeout=embedding_timeout,
    )

    if response.status_code != 200:
        print(f"            FAIL HTTP {response.status_code}")
        print(f"            {response.text[:500]}")
        raise SystemExit(1)

    payload = response.json()
    items = payload.get("data") or []
    if not items:
        print("            FAIL пустой data в ответе")
        raise SystemExit(1)

    dim = len(items[0].get("embedding") or [])
    print(f"            OK  vectors={len(items)}, dim={dim}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка Cloud.ru Foundation Models API")
    parser.add_argument(
        "--env",
        default=None,
        help="Путь к env-файлу (по умолчанию: .env → .env.example → ~/.openclaw/.env)",
    )
    parser.add_argument("--llm-only", action="store_true", help="Только chat/completions")
    parser.add_argument(
        "--embeddings-only",
        action="store_true",
        help="Только embeddings",
    )
    args = parser.parse_args()

    loaded_paths = load_env(args.env)
    api_key = get_api_key()

    if loaded_paths:
        print("Env:")
        for path in loaded_paths:
            print(f"  - {path}")
    else:
        print("Env: переменные только из окружения процесса")
    print(f"Key: {API_KEY_ENV} = {'*' * 8}{api_key[-4:] if len(api_key) >= 4 else '****'}")
    print()

    run_llm = not args.embeddings_only
    run_embeddings = not args.llm_only

    if run_llm:
        check_llm(api_key)
        print()

    if run_embeddings:
        check_embeddings(api_key)
        print()

    print("Готово: Cloud.ru API доступен.")


if __name__ == "__main__":
    main()
