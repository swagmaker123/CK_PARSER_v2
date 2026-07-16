"""
ИФТ-скрипт: скачать Excel из IMAP → разослать HTML-дайджесты по ЦК.

Cron (пример, 5-е число месяца в 09:00):
  0 9 5 * * /path/to/ift_server/venv/bin/python /path/to/ift_server/main.py >> /path/to/ift_server/logs/cron_output.log 2>&1
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
import ssl
import sys
import tempfile
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from mailer import (
    DEFAULT_SMTP_HOST,
    DEFAULT_SMTP_PORT,
    require_llm_columns_for_send,
    resolve_email_header_path,
    send_news_email,
)

PACKAGE_ROOT = Path(__file__).resolve().parent
CK_COLUMN = "Наименование ЦК"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class FatalError(Exception):
    """Ошибка, после которой скрипт завершается с ненулевым кодом."""


def setup_logging() -> logging.Logger:
    log_dir = PACKAGE_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "script_execution.log"

    logger = logging.getLogger("ift_server")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    return logger


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise FatalError(f"Не задана переменная окружения: {name}")
    return value


def _decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_email_address(from_header: str) -> str:
    match = re.search(r"<([^>]+)>", from_header or "")
    if match:
        return match.group(1).strip().lower()
    return (from_header or "").strip().lower()


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("._")
    return cleaned or "attachment.xlsx"


def _iter_parts(msg: Message):
    if msg.is_multipart():
        for part in msg.walk():
            yield part
    else:
        yield msg


def _find_xlsx_attachment(msg: Message) -> tuple[str, bytes] | None:
    for part in _iter_parts(msg):
        if part.get_content_maintype() == "multipart":
            continue

        filename = part.get_filename()
        if filename:
            filename = _decode_mime_header(filename)
        else:
            filename = ""

        is_xlsx_name = filename.lower().endswith(".xlsx")
        if not is_xlsx_name:
            continue

        payload = part.get_payload(decode=True)
        if not payload:
            continue

        return _safe_filename(filename), payload

    return None


def download_latest_xlsx_from_imap(logger: logging.Logger) -> Path:
    host = _require_env("IMAP_HOST")
    port = int(os.getenv("IMAP_PORT", "993").strip() or "993")
    login = _require_env("IMAP_LOGIN")
    password = _require_env("IMAP_PASSWORD")
    sender = os.getenv("IMAP_SENDER", "newsparser@internet.ru").strip().lower()
    folder = os.getenv("IMAP_FOLDER", "INBOX").strip() or "INBOX"
    use_ssl = os.getenv("IMAP_SSL", "true").strip().lower() not in {"0", "false", "no"}

    downloads_dir = PACKAGE_ROOT / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    client: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None
    try:
        if use_ssl or port == 993:
            client = imaplib.IMAP4_SSL(host, port, ssl_context=context)
        else:
            client = imaplib.IMAP4(host, port)
            client.starttls(ssl_context=context)

        client.login(login, password)
        logger.info("Успешное подключение к почтовому ящику IMAP (%s:%s)", host, port)

        status, _ = client.select(folder)
        if status != "OK":
            raise FatalError(f"Не удалось открыть папку IMAP: {folder}")

        # Ищем письма от нужного отправителя (не просто последнее в ящике).
        status, data = client.search(None, "FROM", f'"{sender}"')
        if status != "OK" or not data or not data[0]:
            raise FatalError(f"Нет писем от отправителя {sender}")

        message_ids = data[0].split()
        for msg_id in reversed(message_ids):
            status, fetched = client.fetch(msg_id, "(RFC822)")
            if status != "OK" or not fetched or not fetched[0]:
                continue

            raw = fetched[0][1]
            msg = email.message_from_bytes(raw)
            from_addr = _extract_email_address(_decode_mime_header(msg.get("From")))
            if from_addr != sender:
                continue

            attachment = _find_xlsx_attachment(msg)
            if attachment is None:
                logger.warning(
                    "В письме от %s (Message-ID=%s) отсутствует .xlsx вложение",
                    sender,
                    _decode_mime_header(msg.get("Message-ID")) or msg_id.decode(errors="replace"),
                )
                continue

            filename, payload = attachment
            target = downloads_dir / filename
            if target.exists():
                stem, suffix = target.stem, target.suffix
                idx = 1
                while target.exists():
                    target = downloads_dir / f"{stem}_{idx}{suffix}"
                    idx += 1

            target.write_bytes(payload)
            logger.info(
                "Найдено письмо от %s, скачан файл: %s",
                sender,
                target.name,
            )
            return target

        raise FatalError(
            f"У писем от {sender} нет подходящего .xlsx вложения"
        )
    except FatalError:
        raise
    except Exception as exc:
        raise FatalError(f"Ошибка подключения/чтения IMAP: {exc}") from exc
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass


def load_recipients(path: Path, logger: logging.Logger) -> list[dict]:
    if not path.is_file():
        raise FatalError(f"Не найден файл получателей: {path}")

    df = pd.read_excel(path)
    columns = {str(c).strip().lower(): c for c in df.columns}
    if "mail" not in columns or "ck" not in columns:
        raise FatalError(
            f"В {path.name} нужны колонки mail и ck (найдены: {list(df.columns)})"
        )

    mail_col = columns["mail"]
    ck_col = columns["ck"]
    recipients: list[dict] = []

    for _, row in df.iterrows():
        mail_raw = row.get(mail_col)
        ck_raw = row.get(ck_col)
        if pd.isna(mail_raw) or pd.isna(ck_raw):
            continue

        mail = str(mail_raw).strip()
        ck_text = str(ck_raw).strip()
        if not mail or not ck_text:
            continue

        if not EMAIL_RE.match(mail):
            logger.warning("Некорректный email (пропущен): %s", mail)
            continue

        ck_list = [part.strip() for part in ck_text.split(",") if part.strip()]
        if not ck_list:
            continue

        recipients.append({"mail": mail, "ck": ck_list})

    logger.info(
        "Успешно валидировано email-адресов получателей: %s",
        len(recipients),
    )
    return recipients


def recipients_for_ck(recipients: list[dict], ck_name: str) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()
    for item in recipients:
        if ck_name not in item["ck"]:
            continue
        mail = item["mail"]
        if mail in seen:
            continue
        seen.add(mail)
        emails.append(mail)
    return emails


def send_per_ck(
    news_path: Path,
    recipients: list[dict],
    logger: logging.Logger,
) -> int:
    smtp_login = _require_env("SMTP_LOGIN")
    smtp_password = _require_env("SMTP_PASSWORD")
    smtp_host = os.getenv("SMTP_HOST", "").strip() or DEFAULT_SMTP_HOST
    smtp_port = int(os.getenv("SMTP_PORT", str(DEFAULT_SMTP_PORT)).strip() or DEFAULT_SMTP_PORT)
    email_from = os.getenv("EMAIL_FROM", "").strip() or None
    send_top_n = int(os.getenv("SEND_TOP_N", "10").strip() or "10")
    header_path = resolve_email_header_path()

    news_df = pd.read_excel(news_path)
    require_llm_columns_for_send(news_df, news_path)

    if CK_COLUMN not in news_df.columns:
        raise FatalError(f"В новостном Excel нет колонки «{CK_COLUMN}»")

    ck_values = (
        news_df[CK_COLUMN]
        .dropna()
        .astype(str)
        .map(str.strip)
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )

    if not ck_values:
        raise FatalError(f"В новостном Excel нет значений в колонке «{CK_COLUMN}»")

    sent_count = 0
    for ck_name in ck_values:
        ck_df = news_df[news_df[CK_COLUMN].astype(str).str.strip() == ck_name].copy()
        if ck_df.empty:
            logger.warning("ЦК %s: нет новостей, пропуск", ck_name)
            continue

        emails = recipients_for_ck(recipients, ck_name)
        if not emails:
            logger.warning("ЦК %s: нет получателей, пропуск", ck_name)
            continue

        with tempfile.NamedTemporaryFile(
            prefix=f"digest_{_safe_filename(ck_name)}_",
            suffix=".xlsx",
            delete=False,
        ) as tmp:
            temp_path = Path(tmp.name)

        try:
            ck_df.to_excel(temp_path, index=False)
            send_news_email(
                smtp_login=smtp_login,
                smtp_password=smtp_password,
                recipients=emails,
                subject=f"Дайджест новостей — {ck_name}",
                final_df=ck_df,
                header_image_path=header_path,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                email_from=email_from,
                latest_news_limit=send_top_n,
                attachments=[str(temp_path)],
                report_title=f"Новостной дайджест — {ck_name}",
                report_subtitle="Топ новостей по llm_score",
            )
        except Exception as exc:
            logger.error("Ошибка отправки для ЦК %s: %s", ck_name, exc)
            raise FatalError(f"Ошибка SMTP/отправки для ЦК {ck_name}: {exc}") from exc
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

        logger.info("Отправлено письмо для ЦК %s на %s адресов", ck_name, len(emails))
        sent_count += 1

    return sent_count


def main() -> int:
    load_dotenv(PACKAGE_ROOT / ".env", override=True)
    logger = setup_logging()
    logger.info("Запуск скрипта ИФТ-рассылки")

    try:
        news_path = download_latest_xlsx_from_imap(logger)

        recipients_path = Path(
            os.getenv("RECIPIENTS_XLSX", "").strip() or (PACKAGE_ROOT / "recipients.xlsx")
        )
        if not recipients_path.is_absolute():
            recipients_path = PACKAGE_ROOT / recipients_path

        recipients = load_recipients(recipients_path, logger)
        if not recipients:
            raise FatalError("После валидации не осталось получателей")

        sent = send_per_ck(news_path, recipients, logger)
        if sent == 0:
            logger.warning("Не отправлено ни одного письма (нет пар ЦК+получатели)")
        logger.info("Успешное завершение работы скрипта (писем по ЦК: %s)", sent)
        return 0
    except FatalError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.exception("Неожиданная ошибка: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
