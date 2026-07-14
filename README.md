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

Шаги **раздельные** — каждый своей командой.

### 1. Парсинг и фильтры — `python main.py`

Собирает новости по источникам, режет фильтрами ЦК (ПС / ССЭМ / Налоги), **дописывает** строки в активный Excel-период.

```powershell
python main.py
```

По умолчанию: все источники, все ЦК, 30 дней, refresh последних 2 дней. LLM и почта **не** запускаются.

```powershell
# только за 1 день (сегодня / окно в 1 день)
python main.py --days 1

# только из кэша, без сайтов
python main.py --export-only --days 30

# один источник / один ЦК
python main.py --source cbr
python main.py --ck taxes
```

**Windows (venv):** `.\venv\Scripts\activate` затем `python main.py`  
**Linux / macOS:** `source venv/bin/activate` затем `python main.py`

### 2. Enrich (1-й LLM-проход) — `--enrich` / `--enrich-only`

Суммаризация, оценка релевантности и semantic dedupe:

- `llm_summary` — краткое резюме
- `llm_score` — оценка 0–100
- удаление векторных дублей внутри ЦК

```powershell
# парсинг + enrich в одном запуске
python main.py --enrich

# только enrich по уже собранному активному Excel
python main.py --enrich-only
```

Топ (`top_rank` / `is_top_news`) здесь **не** считается.

Checkpoint каждые 10 строк (`ENRICH_CHECKPOINT_EVERY` в `.env`). При обрыве — снова `--enrich-only`.

### 3. Ranking (2-й LLM-проход) — `--rank-only`

Топ **10** основных + **5** резервных (= топ-15 по каждому ЦК). Нужен Excel уже с `llm_score`.

В `.env` для 2-го прохода нужно как минимум:

```text
LLM_MAX_TOKENS=4500
```

(меньше — ответ ранжирования часто обрезается.)

```powershell
python main.py --rank-only --top-n 10 --reserve-n 5
```

Обычно раз в месяц (cron), по активному периоду. Пишет `top_rank`, `is_top_news`.

### 4. Отправка на почту — `--send-only`

Отдельный шаг. Шлёт письмо с Excel во вложении. После успешной отправки **активного** файла период закрывается → копия в `output/sent/`, следующий парсинг откроет новый файл.

```powershell
# короткое письмо + только Excel
python main.py --send-only output/news_2026-07-01_2026-07-31.xlsx --plain

# HTML-письмо (нужна шапка assets/email_header.png)
python main.py --send-only output/news_2026-07-01_2026-07-31.xlsx
```

В `.env`:

```text
SMTP_LOGIN=...
SMTP_PASSWORD=...
EMAIL_FROM=you@example.com
DEFAULT_RECIPIENTS=user@example.com,other@example.com
```

Есть также `--send` (отправить после текущего прогона), но рассылку удобнее держать отдельно после `--rank-only`.

| Аргумент | Описание |
|---|---|
| `--source` | Один источник: `banki`, `cbr`, `garant`, `interfax`, `kommersant`, `minfin`, `nalog`, `palata`, `rbc`, `consultant` |
| `--ck` | ID профиля ЦК (`payment_systems`, `ssem`, `taxes`) или `all` |
| `--days` | Окно парсинга в днях (по умолчанию 30) |
| `--refresh-days` | Сколько последних дней перекачать заново (мин. 2) |
| `--export-only` | Excel из кэша, без загрузки сайтов |
| `--enrich` | После парсинга: суммаризация + score + dedupe |
| `--enrich-only` | То же по активному периоду (или `--output`), без парсинга |
| `--rank-only` | 2-й проход: топ-10 + 5 резерв по ЦК |
| `--output` | Явный Excel для enrich/rank (иначе активный период) |
| `--top-n` / `--reserve-n` | Размер топа / резерва для `--rank-only` (10 / 5) |
| `--send-only` | Только отправить указанный Excel |
| `--send` | Отправить письмо после текущего прогона |
| `--send-to` | Адресаты (иначе `DEFAULT_RECIPIENTS`) |
| `--plain` | Короткое письмо + только Excel во вложении |
| `--email-header` | Картинка шапки для HTML |

Промпты LLM: `llm/ranking_prompts/`. Подробнее: [LLM_AUDIT_RANKING.md](LLM_AUDIT_RANKING.md).

### Настройка LLM / модели

Переменные (ключ API, `LLM_MODEL`, `LLM_MAX_TOKENS`, embeddings и т.д.) берутся так:

1. **`.env` в корне проекта** — основной источник  
2. если переменной там нет → **`~/.openclaw/.env`** (fallback)

То, что уже задано в проектном `.env`, OpenClaw не перебивает.

```text
FOUNDATION_MODELS_API_KEY=...
LLM_MODEL=ai-sage/GigaChat3-10B-A1.8B
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=4500
LLM_TEXT_TRUNCATE=8000
```

Для `--rank-only` минимум `LLM_MAX_TOKENS=4500`.

## Результат (Excel)

Один **активный** файл на период (не Excel на каждый день):

```text
output/news_YYYY-MM-DD_YYYY-MM-DD.xlsx   # FROM → TO (начало периода → последняя новость)
output/.active_workbook                  # какой файл сейчас активный
```

`python main.py` / `--export-only` **дописывает** новые строки (дедуп по ссылке + ЦК). Уже обогащённые строки не затираются.

После `--send-only` / `--send` по активному файлу:

```text
output/sent/news_YYYY-MM-DD_YYYY-MM-DD.xlsx
```

Активный файл из `output/` удаляется, маркер сбрасывается — следующий парсинг открывает новый период.

Базовые колонки:

- `Дата новости`
- `Заголовок статьи`
- `Полный текст`
- `Ссылка на источник`
- `Источник`
- `Наименование ЦК` — ПС / ССЭМ / Налоги
- `Ключевые слова` — сработавшие правила фильтра

После `--enrich` / `--enrich-only`:

- `llm_summary` — выжимка новости для ленты и рассылки
- `llm_score` — оценка релевантности для ЦК (0–100)

После `--rank-only`:

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
