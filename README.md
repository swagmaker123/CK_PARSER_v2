# CK PARSER

Парсер новостей по банковским ЦК с фильтрами, Excel-выгрузкой и LLM-постобработкой (audit ranking).

Профили в `filters/ck/`:

- `payment_systems` — ПС
- `ssem` — ССЭМ
- `taxes` — Налоги

## Источники

По умолчанию парсятся все источники из списка ниже (в таком порядке):

| `--source` | Название в Excel |
|---|---|
| `banki` | Банки.ру |
| `cbr` | Центробанк |
| `garant` | Гарант.ру |
| `interfax` | Interfax |
| `minfin` | МинФин |
| `nalog` | ФНС |
| `palata` | Палата НК |
| `rbc` | РБК |
| `consultant` | Consultant |

Парсер Kommersant есть в `parsers/kommersant/`, но в текущем CLI не подключён к `--source`.

## Установка

```powershell
cd C:\Users\asus\Desktop\CK_PARSER
python -m venv venv
.\venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

Для LLM-постобработки нужен ключ API (см. раздел ниже).

## Запуск парсинга

```powershell
.\venv\Scripts\activate
python main.py
```

По умолчанию: все источники, все ЦК, 30 дней. Последние 2 дня всегда перекачиваются (`--refresh-days`, минимум 2).

Частые варианты:

```powershell
python main.py --days 30
python main.py --days 30 --refresh-days 30
python main.py --source cbr
python main.py --source rbc --ck payment_systems
python main.py --ck taxes
python main.py --export-only --days 30
python main.py --enrich
```

| Аргумент | Описание |
|---|---|
| `--source` | Один источник: `banki`, `cbr`, `garant`, `interfax`, `minfin`, `nalog`, `palata`, `rbc`, `consultant` |
| `--ck` | ID профиля ЦК (`payment_systems`, `ssem`, `taxes`) или `all` (по умолчанию) |
| `--days` | Окно парсинга в днях (по умолчанию 30) |
| `--refresh-days` | Сколько последних дней не брать из кэша, а скачать заново (мин. 2) |
| `--export-only` | Только собрать Excel из кэша, без загрузки сайтов |
| `--enrich` | После парсинга запустить LLM audit ranking по готовому Excel |
| `--enrich-only` | Только LLM audit ranking по Excel (без парсинга) |
| `--output` | Путь к Excel для `--enrich-only` |
| `--top-n` | Размер основного топа (по умолчанию 10) |
| `--reserve-n` | Размер резерва после топа (по умолчанию 5) |

`--export-only` читает уже отфильтрованный кэш. Если менялись правила фильтра — сначала обычный `python main.py` (пересбор из raw-кэша), потом при необходимости `--export-only`.

## LLM audit ranking

После сборки Excel можно прогнать двухэтапную LLM-постобработку:

1. **Первый проход** — по каждой новости: `llm_summary`, `llm_score`, отбор кандидатов (`llm_score >= 70`, максимум 30 кандидатов на ЦК).
2. **Второй проход** — ранжирование кандидатов, топ-10 + резерв, колонки `top_rank` и `is_top_news`.

Промпты для каждого ЦК: `llm/ranking_prompts/`.

```powershell
# парсинг + LLM сразу
python main.py --enrich

# только LLM по Excel за сегодня
python main.py --enrich-only

# LLM по конкретному файлу и ЦК
python main.py --enrich-only --output output/news_2026-06-25.xlsx --ck payment_systems
```

Подробнее: [LLM_AUDIT_RANKING.md](LLM_AUDIT_RANKING.md).

### Настройка LLM

`main.py` загружает переменные из `~/.openclaw/.env`.

Минимум:

```text
FOUNDATION_MODELS_API_KEY=...
```

Опционально:

```text
LLM_MODEL=ai-sage/GigaChat3-10B-A1.8B
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=4096
LLM_TEXT_TRUNCATE=8000
```

## Результат

Один Excel на прогон:

```text
output/news_YYYY-MM-DD.xlsx
```

Базовые колонки:

- `Дата новости`
- `Заголовок статьи`
- `Полный текст`
- `Ссылка на источник`
- `Источник`
- `Наименование ЦК` — ПС / ССЭМ / Налоги
- `Ключевые слова` — сработавшие правила фильтра

После `--enrich` / `--enrich-only` добавляются:

- `llm_summary` — выжимка новости для ленты и рассылки
- `llm_score` — оценка релевантности для ЦК (0–100)
- `top_rank` — место в ранжировании по ЦК (1–15)
- `is_top_news` — входит ли новость в топ-10 по своему ЦК

## Кэш

Сырой кэш (все статьи дня без фильтра):

```text
cache/{источник}/raw/cache.json
```

По каждому ЦК (прошедшие фильтр):

```text
cache/{источник}/{ck_id}/cache.json
```

Пример: `cache/cbr/payment_systems/cache.json`.

Кэш хранится в репозитории для воспроизводимости выгрузок.

## Лог

Один файл на прогон:

```text
logs/run_YYYY-MM-DD_HH-MM-SS.log
```

## Фильтры

Правила ЦК: `filters/ck/{ck_id}/rules.py` (в файле — `PROFILE`).

## Структура

```text
main.py                    CLI
parsers/                   парсеры источников
config/sources/            конфиги источников
filters/ck/                правила ЦК
export/                    Excel, enricher, audit_ranker
llm/                       клиент LLM, audit ranking, промпты
mailer.py                  отправка Excel по почте
cache/                     кэш парсинга
output/                    Excel-выгрузки
logs/                      логи прогонов
LLM_AUDIT_RANKING.md       документация по LLM-постобработке
```
