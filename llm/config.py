import os
import json
import pathlib

# ─── OpenClaw config ──────────────────────────────────────────────────────────

_OPENCLAW_CONFIG_PATH = pathlib.Path(
    os.getenv("OPENCLAW_CONFIG", str(pathlib.Path.home() / ".openclaw" / "openclaw.json"))
)

# Provider-префикс, который OpenClaw использует в openclaw.json (нужно убрать для API)
_PROVIDER_PREFIX = "custom-foundation-models-api-cloud-ru/"


def _strip_provider(model: str | None) -> str | None:
    """Убирает provider-префикс: 'custom-foundation-models-api-cloud-ru/zai-org/GLM-5.2' → 'zai-org/GLM-5.2'"""
    if not model:
        return None
    if model.startswith(_PROVIDER_PREFIX):
        return model[len(_PROVIDER_PREFIX):]
    return model


def _load_openclaw_model_config() -> tuple[str | None, list[str]]:
    """
    Читает openclaw.json и возвращает (primary_model, fallback_models).
    Модели очищены от provider-префикса.
    """
    try:
        with open(_OPENCLAW_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        model_cfg = (
            cfg.get("agents", {})
            .get("defaults", {})
            .get("model", {})
        )
        primary = _strip_provider(model_cfg.get("primary"))
        fallbacks = [
            _strip_provider(m) or m
            for m in model_cfg.get("fallbacks", [])
        ]
        fallbacks = [m for m in fallbacks if m]
        return primary, fallbacks
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return None, []


_oc_primary, _oc_fallbacks = _load_openclaw_model_config()

# ─── LLM config ───────────────────────────────────────────────────────────────
# Приоритет: openclaw.json → .env → дефолт
# (openclaw.json важнее, т.к. OpenClaw runtime может инжектить устаревший LLM_MODEL в env)

# URL API Cloud.ru Foundation Models
LLM_API_URL: str = os.getenv(
    "LLM_API_URL",
    "https://foundation-models.api.cloud.ru/v1/chat/completions",
)

# Основная модель: openclaw.json → .env → дефолт
LLM_MODEL: str = _oc_primary or os.getenv("LLM_MODEL", "zai-org/GLM-5.2")

# Fallback-модели: openclaw.json → .env (через запятую) → пусто
_env_fallbacks = [
    m.strip()
    for m in os.getenv("LLM_FALLBACK_MODELS", "").split(",")
    if m.strip()
]
LLM_FALLBACK_MODELS: list[str] = _oc_fallbacks or _env_fallbacks

# Таймаут на один LLM-запрос (сек). Если основная модель не отвечает за это время —
# переключаемся на fallback. Жёсткий таймаут = LLM_REQUEST_TIMEOUT * 1.5 на fallback.
LLM_REQUEST_TIMEOUT: int = int(os.getenv("LLM_REQUEST_TIMEOUT", "120"))

# Сколько последовательных ошибок основной модели подряд, чтобы сразу
# начинать с fallback (без попытки primary).
LLM_FAIL_THRESHOLD: int = int(os.getenv("LLM_FAIL_THRESHOLD", "3"))

# Количество топ-новостей по умолчанию для пометки на листе
TOP_N: int = int(os.getenv("LLM_TOP_N", "10"))

# Параметры генерации
TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))
MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "4096"))

# Максимальное количество символов текста статьи, передаваемых в промпт
TEXT_TRUNCATE: int = int(os.getenv("LLM_TEXT_TRUNCATE", "8000"))
