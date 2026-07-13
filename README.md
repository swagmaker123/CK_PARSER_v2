# CK PARSER

Парсер новостей по банковским ЦК с фильтрами, Excel-выгрузкой и LLM-постобработкой (audit ranking).

Профили в `filters/ck/`:

- `payment_systems` — ПС
- `ssem` — ССЭМ
- `taxes` — Налоги

## Источники

По умолчанию парсятся все источники (в порядке из `config/sources/registry.py`):

| `--source` | Название в Excel |
|---|---|
| `banki` | Банки.ру |
| `cbr` | Центробанк |
| `garant` | Гарант.ру |
| `interfax` | Interfax |
| `kommersant` | Kommersant |
| `minfin` | МинФин |
| `nalog` | ФНС |
| `palata` | Палата НК |
| `rbc` | РБК |
| `consultant` | Consultant |

Kommersant использует Playwright (Chromium) — нужен `playwright install chromium`. Парсер подгружается только при запуске `--source kommersant`.

## Установка

**Windows (PowerShell):**

```powershell
cd C:\path\to\CK_PARSER
python -m venv venv
.\venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

**Linux / macOS:**

```bash
cd /path/to/CK_PARSER
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
# Chromium + системные библиотеки Linux (libnss3, libatk и т.д.)
playwright install --with-deps chromium
```

На Linux venv активируется через `source venv/bin/activate` (не `.\venv\Scripts\activate`).

`install --with-deps` подтянет OS-пакеты через `apt` (нужен `sudo`). Если команда в venv недоступна под sudo:

```bash
sudo ./venv/bin/playwright install-deps chromium
playwright install chromium
```

Официально поддерживаются Debian 12/13 и Ubuntu 22.04/24.04/26.04. Подробнее: [Playwright — Browsers](https://playwright.dev/python/docs/browsers#install-system-dependencies).

Для Kommersant обязателен Chromium из Playwright (см. выше).

Для LLM-постобработки нужен ключ API (см. раздел ниже).

## Запуск

### Что делает `python main.py` без флагов

**Только сбор данных и Excel.** LLM и почта **не запускаются**.

| Этап | `python main.py` | Нужен флаг |
|------|------------------|------------|
| Парсинг всех источников | ✅ | — |
| Все ЦК (ПС, ССЭМ, Налоги) | ✅ | — |
| 30 дней, refresh последних 2 | ✅ | — |
| Excel в `output/` | ✅ | — |
| LLM enrich | ❌ | `--enrich` |
| Email | ❌ | `--send` |

Полный пайплайн «парсинг → enrich → письмо»:

```bash
python main.py --enrich --send
```

Порядок в одном прогоне:

1. Парсинг → Excel  
2. LLM audit ranking (колонки `llm_score`, `llm_summary`, …)  
3. HTML-письмо + Excel во вложении  

> `--send` **без** `--enrich` в том же запуске завершится ошибкой: в свежем Excel ещё нет `llm_score`.

### Базовый запуск

**Windows:**

```powershell
.\venv\Scripts\activate
python main.py
```

**Linux / macOS:**

```bash
source venv/bin/activate
python main.py
```

По умолчанию: все источники, все ЦК, 30 дней. Последние 2 дня всегда перекачиваются (`--refresh-days`, минимум 2).

### Частые команды

```powershell
# только парсинг + Excel (по умолчанию)
python main.py

# парсинг + LLM
python main.py --enrich

# парсинг + LLM + HTML-письмо (полный цикл)
python main.py --enrich --send

# только Excel из кэша, без сайтов
python main.py --export-only --days 30

# один источник / один ЦК
python main.py --source cbr
python main.py --source rbc --ck payment_systems
python main.py --ck taxes

# LLM по уже готовому Excel
python main.py --enrich-only --output output/news_2026-06-25.xlsx

# только отправка enrich-Excel
python main.py --send-only output/news_2026-06-25.xlsx
```

| Аргумент | Описание |
|---|---|
| `--source` | Один источник: `banki`, `cbr`, `garant`, `interfax`, `kommersant`, `minfin`, `nalog`, `palata`, `rbc`, `consultant` |
| `--ck` | ID профиля ЦК (`payment_systems`, `ssem`, `taxes`) или `all` (по умолчанию) |
| `--days` | Окно парсинга в днях (по умолчанию 30) |
| `--refresh-days` | Сколько последних дней не брать из кэша, а скачать заново (мин. 2) |
| `--export-only` | Только собрать Excel из кэша, без загрузки сайтов |
| `--enrich` | После парсинга запустить LLM audit ranking по готовому Excel |
| `--enrich-only` | Только LLM audit ranking по Excel (без парсинга) |
| `--output` | Путь к Excel для `--enrich-only` |
| `--top-n` | Размер основного топа (по умолчанию 10) |
| `--reserve-n` | Размер резерва после топа (по умолчанию 5) |
| `--send` | После прогона отправить **HTML-письмо** (**обязательно вместе с `--enrich` в том же запуске**, либо enrich-Excel для `--send-only`) |
| `--send-only` | Только отправить enrich-Excel по email (HTML + вложение) |
| `--send-to` | Адресаты email (если не задано — `DEFAULT_RECIPIENTS` из `.env`) |
| `--email-header` | Путь к картинке шапки (по умолчанию `assets/email_header.png`) |
| `--send-top-n` | Сколько новостей показать в письме (default: 10) |
| `--plain` | Короткое письмо + только Excel во вложении (без HTML-карточек) |

`--export-only` читает уже отфильтрованный кэш. Если менялись правила фильтра — сначала обычный `python main.py` (пересбор из raw-кэша), потом при необходимости `--export-only`.

### Email

`--send` / `--send-only` по умолчанию шлют **HTML-письмо** (карточки + Excel). С `--plain` — короткое письмо и только Excel во вложении.

Требования:

1. Excel **после LLM enrich** — в файле должна быть колонка `llm_score`
2. Картинка шапки: **`assets/email_header.png`** (положите файл в папку `assets/`)

Пример:

```powershell
python main.py --enrich-only --output output/news_2026-06-25.xlsx
python main.py --send-only output/news_2026-06-25.xlsx

# или за один прогон
python main.py --enrich --send
```

Другой путь к шапке:

```powershell
python main.py --send-only output/news_2026-06-25.xlsx --email-header assets/my_banner.png
```

или в `.env` проекта:

```text
EMAIL_HEADER_IMAGE=assets/my_banner.png
```

Для `--send` / `--send-only` в `.env` проекта (см. `.env.example`):

```text
SMTP_LOGIN=...
SMTP_PASSWORD=...
EMAIL_FROM=you@example.com
DEFAULT_RECIPIENTS=user@example.com,other@example.com
```

Можно также держать секреты в `~/.openclaw/.env` — он подхватывается как fallback, если переменной нет в `.env` проекта.
## LLM audit ranking

После сборки Excel можно прогнать двухэтапную LLM-постобработку:

1. **Первый проход** — по каждой новости: `llm_summary`, `llm_score`, отбор кандидатов (`llm_score >= 60`, максимум 30 кандидатов на ЦК).
2. **Semantic dedupe** — удаление дублей среди всех строк каждого ЦК (оставляется max `llm_score`).
3. **Второй проход** — ранжирование кандидатов, топ-10 + резерв, колонки `top_rank` и `is_top_news`.

Во время 1-го прохода Excel сохраняется каждые 10 строк (checkpoint). Если процесс оборвался — снова запусти `--enrich-only` по тому же файлу: уже оценённые строки пропустятся. Интервал: `ENRICH_CHECKPOINT_EVERY` в `.env`.

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

`main.py` загружает переменные из `.env` в корне проекта (приоритет), затем из `~/.openclaw/.env` (fallback).

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

## Тесты

```powershell
pip install -r requirements.txt
python -m pytest tests/ -v
```

Проверяются: справочник источников (`config/sources/registry.py`), форматы дат в `--export-only`, алиасы ЦК.

## Фильтры

Правила ЦК: `filters/ck/{ck_id}/rules.py` (в файле — `PROFILE`).

## Структура проекта

```text
main.py                         точка входа, загрузка .env
cli.py                          аргументы командной строки
runner.py                       оркестрация прогона
parsers/                        парсеры источников
config/sources/                 конфиги и registry источников
config/sources/registry.py      единый справочник всех источников
config/ck.py                    справочник ЦК (id, названия, алиасы)
config/export_defaults.py       настройки экспорта для парсеров
filters/ck/                     правила ЦК
export/                         Excel, enricher, from_cache
llm/                            клиент LLM, audit ranking, промпты
dedupe/                         semantic dedupe через Cloud.ru — см. [DEDUPE.md](DEDUPE.md)
common/                         HTTP, кэш, dedupe статей, paths
mailer.py                       HTML-рассылка и Excel-вложение
assets/email_header.png         шапка HTML-письма (положить вручную)
tests/                          pytest-тесты registry и from_cache
cache/                          кэш парсинга
output/                         Excel-выгрузки
logs/                           логи прогонов
LLM_AUDIT_RANKING.md            документация по LLM-постобработке
```

Краткая шпаргалка по запуску: [КАК ЗАПУСТИТЬ.md](КАК ЗАПУСТИТЬ.md).
