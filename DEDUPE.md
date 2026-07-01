# Semantic dedupe

Семантическая дедупликация между **1-м** и **2-м** этапом LLM enrich.

Запускается автоматически при `--enrich` / `--enrich-only`. Отдельной команды нет.

```text
1. LLM scoring   → llm_summary, llm_score
2. Dedupe        → удаление дублей внутри каждого ЦК
3. LLM ranking   → top-10 + резерв
```

---

## Что нужно подключить

Dedupe использует **embedding-модель** — так же, как enrich использует **LLM-модель**.

Два варианта:

| Вариант | Что нужно | Интернет |
|---|---|---|
| **Cloud.ru** | `EMBEDDING_MODEL` + `FOUNDATION_MODELS_API_KEY` | да |
| **Local** | папка `EMBEDDING_MODEL_PATH` + `sentence-transformers` | нет |

Если ничего не настроено — dedupe **пропускается**, enrich работает дальше.

---

## Вариант 1: Cloud.ru (как LLM)

Подходит, если LLM уже ходит в Cloud.ru Foundation Models.

### Шаг 1. API-ключ

Тот же ключ, что для LLM — в `~/.openclaw/.env`:

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

### Шаг 3. Backend

```text
DEDUPE_BACKEND=cloud
```

### Полный пример `.env` (cloud)

```text
# LLM (уже должно быть)
FOUNDATION_MODELS_API_KEY=ваш_ключ
LLM_MODEL=ai-sage/GigaChat3-10B-A1.8B

# Embeddings для dedupe
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_API_URL=https://foundation-models.api.cloud.ru/v1/embeddings
DEDUPE_BACKEND=cloud
DEDUPE_ENABLED=true
DEDUPE_SIMILARITY_THRESHOLD=0.88
```

### Запуск

```powershell
python main.py --enrich-only --ck payment_systems
```

В логе:

```text
Semantic dedupe: cloud embeddings, model=BAAI/bge-m3
```

---

## Вариант 2: Local (офлайн)

### Шаг 1. Зависимости

```powershell
pip install sentence-transformers numpy torch
```

### Шаг 2. Скачать модель

Положить в `./bge-m3/` (или другой путь):

```text
CK_PARSER/
  bge-m3/          ← сюда файлы модели BAAI/bge-m3
```

Папка в `.gitignore`, в git не коммитится.

### Шаг 3. Путь и backend

```text
EMBEDDING_MODEL_PATH=./bge-m3
EMBEDDING_DEVICE=cpu
DEDUPE_BACKEND=local
```

### Полный пример `.env` (local)

```text
DEDUPE_ENABLED=true
DEDUPE_BACKEND=local
EMBEDDING_MODEL_PATH=./bge-m3
EMBEDDING_DEVICE=cpu
DEDUPE_SIMILARITY_THRESHOLD=0.88
```

---

## Вариант 3: Auto (по умолчанию)

```text
DEDUPE_BACKEND=auto
```

Логика:

1. Если задан `EMBEDDING_MODEL` и есть `FOUNDATION_MODELS_API_KEY` → **cloud**
2. Иначе если есть папка `EMBEDDING_MODEL_PATH` и установлен `sentence-transformers` → **local**
3. Иначе dedupe пропускается

---

## Все переменные

### Embeddings

| Переменная | По умолчанию | Описание |
|---|---|---|
| `EMBEDDING_MODEL` | *(пусто)* | Имя модели в Cloud.ru (для cloud) |
| `EMBEDDING_API_URL` | `https://foundation-models.api.cloud.ru/v1/embeddings` | URL embeddings API |
| `EMBEDDING_MODEL_PATH` | `./bge-m3` | Путь к локальной модели |
| `EMBEDDING_DEVICE` | `cpu` | `cpu` или `cuda` (только local) |
| `EMBEDDING_BATCH_SIZE` | `32` | Размер батча запросов |
| `EMBEDDING_TIMEOUT` | `120` | Таймаут HTTP, сек |
| `FOUNDATION_MODELS_API_KEY` | — | API-ключ Cloud.ru (общий с LLM) |

### Dedupe

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DEDUPE_ENABLED` | `true` | `false` — отключить dedupe |
| `DEDUPE_BACKEND` | `auto` | `cloud`, `local` или `auto` |
| `DEDUPE_SIMILARITY_THRESHOLD` | `0.88` | Порог cosine similarity |
| `DEDUPE_FULL_TEXT_FALLBACK_CHARS` | `1000` | Fallback из полного текста |

Дефолты в коде: `dedupe/config.py`.

---

## Как работает dedupe

1. Берёт **все строки** каждого ЦК после 1-го LLM-прохода.
2. Строит текст: `Заголовок` + `llm_summary`.
3. Получает эмбеддинги через выбранный backend.
4. Склеивает дубли (similarity ≥ порога) внутри ЦК.
5. **Удаляет** лишние строки, оставляет одну с **max `llm_score`**.

Порог score / `is_candidate` на dedupe **не влияет**.

### Порог similarity

| Значение | Эффект |
|---|---|
| `0.92+` | Жёстко, только явные дубли |
| `0.88` | По умолчанию |
| `0.85` | Мягче, больше склеек |

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
  embeddings.py   — cloud / local backend
  semantic.py     — поиск и удаление дублей
```

Точка входа: `llm/audit_ranker.py`.

---

## FAQ


**Dedupe не сработал — почему?**  
Смотри лог: `Semantic dedupe пропущен: ...` — там причина (нет ключа, модели, зависимостей).
