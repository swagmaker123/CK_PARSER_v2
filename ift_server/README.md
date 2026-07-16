# ИФТ-пакет: рассылка новостей по ЦК

Автономный скрипт для Linux-сервера (Cron раз в месяц):

1. Забирает последний `.xlsx` из IMAP от `newsparser@internet.ru`
2. Читает справочник `recipients.xlsx` (`mail`, `ck`)
3. Шлёт HTML-дайджест по каждому ЦК через `send_news_email` из локального `mailer.py`

## Состав

```text
ift_server/
  main.py
  mailer.py              # копия HTML-отправки из корня CK_PARSER (standalone)
  run.sh                 # автозапуск на Linux (Cron)
  run.bat                # локальный запуск на Windows
  recipients.xlsx        # положить на сервере (образец: recipients.xlsx.example)
  .env
  requirements.txt
  assets/email_header.png
  downloads/             # скачанные Excel
  logs/script_execution.log
```

При изменении корневого `mailer.py` в CK_PARSER обновите копию `ift_server/mailer.py` (HTML-часть) и замените `PROJECT_ROOT` на корень пакета.

## Установка на Linux

```bash
cd /path/to/ift_server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполните IMAP_* и SMTP_* в .env
cp recipients.xlsx.example recipients.xlsx
# отредактируйте recipients.xlsx
# замените assets/email_header.png на боевую шапку письма
```



## recipients.xlsx


| mail                                          | ck       |
| --------------------------------------------- | -------- |
| [user@sberbank.ru](mailto:user@sberbank.ru)   | ПС, ССЭМ |
| [other@sberbank.ru](mailto:other@sberbank.ru) | Налоги   |


Значения `ck` должны совпадать с колонкой **Наименование ЦК** во входящем Excel: `ПС`, `ССЭМ`, `Налоги`.

## Переменные окружения

См. `.env.example`:

- `IMAP_HOST`, `IMAP_PORT`, `IMAP_LOGIN`, `IMAP_PASSWORD`
- `IMAP_SENDER` (по умолчанию `newsparser@internet.ru`)
- `SMTP_LOGIN`, `SMTP_PASSWORD`, `SMTP_HOST`, `SMTP_PORT`, `EMAIL_FROM`
- опционально: `RECIPIENTS_XLSX`, `EMAIL_HEADER_IMAGE`, `SEND_TOP_N`



## Запуск

Linux:

```bash
chmod +x run.sh
./run.sh
```

Windows (проверка локально):

```bat
run.bat
```

Лог: `logs/script_execution.log`.

## Cron (автозапуск раз в месяц)

На Linux `.bat` не нужен — планировщик это **Cron**, скрипт — `run.sh`.

После деплоя один раз:

```bash
chmod +x /path/to/ift_server/run.sh
crontab -e
```

Строка (5-е число каждого месяца в 09:00):

```cron
0 9 5 * * /path/to/ift_server/run.sh >> /path/to/ift_server/logs/cron_output.log 2>&1
```

## Автотесты

Из корня CK_PARSER (без реального IMAP/SMTP):

```bash
pytest tests/test_ift_server.py -q
```

