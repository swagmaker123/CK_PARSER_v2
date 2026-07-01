from pathlib import Path
from email.message import EmailMessage
import mimetypes
import smtplib
from typing import Iterable


def attach_files(msg: EmailMessage, file_paths: Iterable[str | Path]) -> None:
    for file_path in file_paths:
        path = Path(file_path)
        if not path.exists():
            continue

        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type:
            maintype, subtype = mime_type.split("/", 1)
        else:
            maintype, subtype = "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet",

        with open(path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype=maintype,
                subtype=subtype,
                filename=path.name,
            )


def send_news_email_plain(
    smtp_login: str,
    smtp_password: str,
    recipients: list[str],
    subject: str,
    smtp_host: str = "smtp.mail.ru",
    smtp_port: int = 465,
    attachments: list[str] | None = None,
) -> None:
    if not recipients:
        raise ValueError("Список recipients пуст")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_login
    msg["To"] = ", ".join(recipients)
    msg.set_content("""Рассылка новостей для проведения дальнейшего анализа.
Для добавления к рассылке новых пользователей обратитесь к
GAZelenskiy@sberbank.ru или Stepanova.A.Igorev@sberbank.ru""")

    if attachments:
        attach_files(msg, attachments)

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(smtp_login, smtp_password)
        server.send_message(msg)
