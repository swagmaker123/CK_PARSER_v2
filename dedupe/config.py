import os
from pathlib import Path

from common.paths import PROJECT_ROOT

# Можно выключить dedupe: DEDUPE_ENABLED=false
DEDUPE_ENABLED: bool = os.getenv("DEDUPE_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)

# local | cloud | auto
# auto: cloud если задан EMBEDDING_MODEL, иначе local если есть EMBEDDING_MODEL_PATH
DEDUPE_BACKEND: str = os.getenv("DEDUPE_BACKEND", "auto").strip().lower()

# --- Embeddings (Cloud.ru или local) ---
EMBEDDING_API_URL: str = os.getenv(
    "EMBEDDING_API_URL",
    "https://foundation-models.api.cloud.ru/v1/embeddings",
)
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "").strip()
EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
EMBEDDING_TIMEOUT: int = int(os.getenv("EMBEDDING_TIMEOUT", "120"))
EMBEDDING_MODEL_PATH = Path(
    os.getenv("EMBEDDING_MODEL_PATH", PROJECT_ROOT / "bge-m3")
)
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")

# Тот же ключ, что и для LLM (llm/client.py)
EMBEDDING_API_KEY_ENV = "FOUNDATION_MODELS_API_KEY"

# --- Dedupe logic ---
SIMILARITY_THRESHOLD = float(os.getenv("DEDUPE_SIMILARITY_THRESHOLD", "0.88"))
FULL_TEXT_FALLBACK_CHARS = int(os.getenv("DEDUPE_FULL_TEXT_FALLBACK_CHARS", "1000"))

TITLE_COLUMN = "Заголовок статьи"
SUMMARY_COLUMN = "llm_summary"
FULL_TEXT_COLUMN = "Полный текст"
SCORE_COLUMN = "llm_score"
