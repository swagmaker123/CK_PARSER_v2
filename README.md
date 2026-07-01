# CK PARSER

Парсер новостей Interfax, Kommersant и Consultant с фильтрами по ЦК.

Профили в `filters/ck/`:

- `payment_systems` — ПС
- `ssem` — ССЭМ
- `taxes` — Налоги

## Установка

```powershell
cd C:\Users\asus\Desktop\CK_PARSER
python -m venv venv
.\venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

Kommersant использует Playwright (Chromium).

## Запуск

```powershell
.\venv\Scripts\activate
python main.py
```

По умолчанию: все источники, все ЦК, 30 дней. Последние 2 дня всегда перекачиваются (`--refresh-days`, минимум 2).

Частые варианты:

```powershell
python main.py --days 30
python main.py --days 30 --refresh-days 30
python main.py --source interfax
python main.py --ck taxes
python main.py --export-only --days 30
```

| Аргумент | Описание |
|---|---|
| `--source` | Один источник: `interfax`, `kommersant`, `consultant` |
| `--ck` | Один ЦК или `all` (по умолчанию) |
| `--days` | Окно парсинга в днях (по умолчанию 30) |
| `--refresh-days` | Сколько последних дней не брать из кэша, а скачать заново (мин. 2) |
| `--export-only` | Только собрать Excel из кэша, без загрузки сайтов |

`--export-only` читает уже отфильтрованный кэш. Если менялись правила фильтра — сначала обычный `python main.py` (пересбор из raw-кэша), потом при необходимости `--export-only`.

## Результат

Один Excel на прогон:

```text
output/news_YYYY-MM-DD.xlsx
```

В конце в консоли:

```text
========== РЕЗУЛЬТАТ ==========
Excel: C:\Users\asus\Desktop\CK_PARSER\output\news_2026-06-23.xlsx
```

Колонки:

- `Дата новости`
- `Заголовок статьи`
- `Полный текст`
- `Ссылка на источник`
- `Источник` — Interfax / Kommersant / Consultant
- `Наименование ЦК` — ПС / ССЭМ / Налоги
- `Ключевые слова` — сработавшие правила фильтра

## Кэш

Сырой кэш (все статьи дня без фильтра):

```text
cache/{источник}/raw/cache.json
```

По каждому ЦК (прошедшие фильтр):

```text
cache/{источник}/{ck_id}/cache.json
```

Пример: `cache/interfax/taxes/cache.json`.

## Лог

Один файл на прогон:

```text
logs/run_YYYY-MM-DD_HH-MM-SS.log
```

## Фильтры

Правила ЦК: `filters/ck/{ck_id}/rules.py` (в файле — `PROFILE`).

Проверка фильтров на тестовых примерах:

```powershell
python scripts/check_filters.py
```

## Структура

```text
main.py              CLI
parsers/             Interfax, Kommersant, Consultant
filters/ck/          правила ЦК
export/writer.py     запись Excel
cache/               кэш
output/              Excel
logs/                логи
```
