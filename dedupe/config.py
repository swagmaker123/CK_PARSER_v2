import os

# Можно выключить dedupe: DEDUPE_ENABLED=false
DEDUPE_ENABLED: bool = os.getenv("DEDUPE_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)

# --- Embeddings через Cloud.ru Foundation Models ---
EMBEDDING_API_URL: str = os.getenv(
    "EMBEDDING_API_URL",
    "https://foundation-models.api.cloud.ru/v1/embeddings",
)
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "").strip()
EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
EMBEDDING_TIMEOUT: int = int(os.getenv("EMBEDDING_TIMEOUT", "120"))

# Тот же ключ, что и для LLM (llm/client.py)
EMBEDDING_API_KEY_ENV = "FOUNDATION_MODELS_API_KEY"

# --- Dedupe logic ---
SIMILARITY_THRESHOLD = float(os.getenv("DEDUPE_SIMILARITY_THRESHOLD", "0.88"))
FULL_TEXT_FALLBACK_CHARS = int(os.getenv("DEDUPE_FULL_TEXT_FALLBACK_CHARS", "1000"))

TITLE_COLUMN = "Заголовок статьи"
SUMMARY_COLUMN = "llm_summary"
FULL_TEXT_COLUMN = "Полный текст"
SCORE_COLUMN = "llm_score"
