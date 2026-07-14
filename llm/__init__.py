"""
Пакет llm — LLM-обогащение и ранжирование новостей для CK_PARSER.

Публичный интерфейс:
  llm.audit_ranker.score_and_dedupe_news(df) -> df   # ежедневный enrich
  llm.audit_ranker.rank_top_by_ck(df, top_n, reserve_n) -> df  # 2-й проход
  llm.audit_ranker.audit_rank_news(...) -> df  # полный пайплайн (совместимость)
  llm.client.call_llm_json(prompt) -> dict
"""
