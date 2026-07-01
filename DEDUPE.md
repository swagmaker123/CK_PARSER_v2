# Semantic dedupe

Семантическая дедупликация между **1-м** и **2-м** этапом LLM enrich.

Запускается автоматически при `--enrich` / `--enrich-only`.

```text
1. LLM scoring   → llm_summary, llm_score
2. Dedupe        → удаление дублей внутри каждого ЦК
3. LLM ranking   → top-10 + резерв
```

---

## Что нужно подключить

Embeddings идут **только через Cloud.ru Foundation Models** — так же, как LLM.

Нужно два параметра в `~/.openclaw/.env`:

```text
FOUNDATION_MODELS_API_KEY=ваш_ключ
EMBEDDING_MODEL=BAAI/bge-m3
```

Без них dedupe **пропускается**, enrich работает дальше.

---

## Настройка

### Шаг 1. API-ключ

Тот же ключ, что для LLM:

```text
FOUNDATION_MODELS_API_KEY=ваш_ключ
```

### Шаг 2. Имя embedding-модели

```text
EMBEDDING_MODEL=BAAI/bge-m3
```

Другие модели из каталога Cloud.ru:

- `BAAI/bge-m3`
- `Qwen/Qwen3-Embedding-0.6B`
- `Qwen/Qwen3-VL-Embedding-2B`

Меняешь только `EMBEDDING_MODEL` — как `LLM_MODEL` для chat.

### Полный пример `.env`

```text
# LLM
FOUNDATION_MODELS_API_KEY=ваш_ключ
LLM_MODEL=ai-sage/GigaChat3-10B-A1.8B

# Embeddings для dedupe
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_API_URL=https://foundation-models.api.cloud.ru/v1/embeddings

# Dedupe
DEDUPE_ENABLED=true
DEDUPE_SIMILARITY_THRESHOLD=0.88
```

---

## Все переменные

### Embeddings

| Переменная | По умолчанию | Описание |
|---|---|---|
| `EMBEDDING_MODEL` | *(пусто)* | Имя embedding-модели в Cloud.ru |
| `EMBEDDING_API_URL` | `https://foundation-models.api.cloud.ru/v1/embeddings` | URL embeddings API |
| `EMBEDDING_BATCH_SIZE` | `32` | Размер батча запросов |
| `EMBEDDING_TIMEOUT` | `120` | Таймаут HTTP, сек |
| `FOUNDATION_MODELS_API_KEY` | — | API-ключ (общий с LLM) |

### Dedupe

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DEDUPE_ENABLED` | `true` | `false` — отключить dedupe |
| `DEDUPE_SIMILARITY_THRESHOLD` | `0.88` | Порог cosine similarity |
| `DEDUPE_FULL_TEXT_FALLBACK_CHARS` | `1000` | Fallback из полного текста, если нет summary |

Дефолты в коде: `dedupe/config.py`.

---

## Как работает

1. Берёт **все строки** каждого ЦК после 1-го LLM-прохода.
2. Строит текст: `Заголовок` + `llm_summary`.
3. Отправляет в Cloud.ru embeddings API.
4. Склеивает дубли (similarity ≥ порога) внутри ЦК.
5. **Удаляет** лишние строки, оставляет одну с **max `llm_score`**.

### Порог similarity

| Значение | Эффект |
|---|---|
| `0.92+` | Жёстко, только явные дубли |
| `0.88` | По умолчанию |
| `0.85` | Мягче, больше склеек |

---

## Запуск

```powershell
python main.py --enrich-only --ck payment_systems
python main.py --enrich
```

В логе:

```text
Semantic dedupe: cloud embeddings, model=BAAI/bge-m3
ЦК payment_systems: semantic dedupe удалит 3 строк из 47
Semantic dedupe завершён: удалено строк=3
```

---

## Отключить dedupe

```text
DEDUPE_ENABLED=false
```

---

## Структура кода

```text
dedupe/
  config.py       — env-настройки
  embeddings.py   — Cloud.ru embeddings API
  semantic.py     — поиск и удаление дублей
```

Точка входа: `llm/audit_ranker.py`.

---

## FAQ

**Чем `EMBEDDING_MODEL` отличается от `LLM_MODEL`?**  
`LLM_MODEL` — chat для scoring/ranking. `EMBEDDING_MODEL` — векторы для dedupe. Один API-ключ.

**Dedupe не сработал?**  
Смотри лог: `Semantic dedupe пропущен: ...` — нет ключа или `EMBEDDING_MODEL`.

**Нужен интернет?**  
Да, embeddings всегда через Cloud.ru API.
