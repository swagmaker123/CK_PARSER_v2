# config/llm.py
import os

# Включить LLM-обогащение по умолчанию
LLM_ENABLED: bool = os.getenv("LLM_ENABLED", "false").lower() in ("1", "true", "yes")

# Количество топ-новостей на листе по умолчанию
TOP_N: int = int(os.getenv("LLM_TOP_N", "10"))

# Минимальный score для включения в отчёт (зарезервировано)
SCORE_THRESHOLD: int = int(os.getenv("LLM_SCORE_THRESHOLD", "0"))
