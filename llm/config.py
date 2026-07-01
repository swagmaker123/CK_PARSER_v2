import os

# URL API Cloud.ru Foundation Models
LLM_API_URL: str = os.getenv(
    "LLM_API_URL",
    "https://foundation-models.api.cloud.ru/v1/chat/completions",
)

# Модель для вызова
LLM_MODEL: str = os.getenv("LLM_MODEL", "ai-sage/GigaChat3-10B-A1.8B")

# Количество топ-новостей по умолчанию для пометки на листе
TOP_N: int = int(os.getenv("LLM_TOP_N", "10"))

# Параметры генерации
TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))
MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "4096"))

# Максимальное количество символов текста статьи, передаваемых в промпт
TEXT_TRUNCATE: int = int(os.getenv("LLM_TEXT_TRUNCATE", "8000"))
