from pathlib import Path
from email.message import EmailMessage
from email.utils import make_msgid
from urllib.parse import urlparse
import mimetypes
import os
import smtplib
from typing import Iterable

import pandas as pd

from common.paths import PROJECT_ROOT


LLM_SEND_REQUIRED_COLUMNS = ("llm_score",)

DEFAULT_EMAIL_HEADER_FILENAME = "email_header.png"
DEFAULT_EMAIL_HEADER_PATH = Path("assets") / DEFAULT_EMAIL_HEADER_FILENAME

DEFAULT_REQUIRED_COLUMNS = [
    "Дата новости",
    "Заголовок статьи",
    "Полный текст",
    "Ссылка на источник",
    "Источник",
    "Ключевые слова",
    "llm_score",
    "llm_summary",
]


def resolve_email_header_path(custom_path=None) -> Path:
    if custom_path:
        path = Path(custom_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
    else:
        env_path = os.getenv("EMAIL_HEADER_IMAGE", "").strip()
        if env_path:
            path = Path(env_path)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
        else:
            path = PROJECT_ROOT / DEFAULT_EMAIL_HEADER_PATH

    if not path.is_file():
        raise SystemExit(
            "Ошибка: не найдена картинка для HTML-письма.\n"
            f"Ожидается файл: {path}\n"
            f"Положите шапку как assets/{DEFAULT_EMAIL_HEADER_FILENAME} "
            "или задайте EMAIL_HEADER_IMAGE в .env / --email-header."
        )

    return path


def require_llm_columns_for_send(df: pd.DataFrame, excel_path=None) -> None:
    missing = [column for column in LLM_SEND_REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        path_hint = f" ({excel_path})" if excel_path else ""
        missing_text = ", ".join(missing)
        raise SystemExit(
            f"Ошибка: отправка по email возможна только после LLM enrich{path_hint}.\n"
            f"В Excel нет колонок: {missing_text}.\n"
            "Сначала запустите enrich, например:\n"
            "  python main.py --enrich-only --output output/news_YYYY-MM-DD.xlsx\n"
            "или полный прогон с флагом --enrich."
        )


def _safe_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value)


def _normalize_keywords(value) -> list[str]:
    if value is None:
        return []

    if isinstance(value, float) and pd.isna(value):
        return []

    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]

    if isinstance(value, tuple) or isinstance(value, set):
        return [str(x).strip() for x in value if str(x).strip()]

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return []

        if cleaned.startswith("[") and cleaned.endswith("]"):
            cleaned = cleaned[1:-1].strip()
            if not cleaned:
                return []
            parts = [x.strip().strip("'").strip('"') for x in cleaned.split(",")]
            return [x for x in parts if x]

        return [cleaned]

    return [str(value).strip()] if str(value).strip() else []


def build_plain_text_report(news_df: pd.DataFrame, total_count: int) -> str:
    lines = []
    lines.append("Новостной дайджест")
    lines.append("")
    lines.append(f"Всего найдено новостей: {total_count}")
    lines.append("Топ новостей по llm_score:")
    lines.append("")

    if news_df is None or news_df.empty:
        lines.append("Новостей для отображения не найдено.")
        return "\n".join(lines)

    for idx, (_, row) in enumerate(news_df.iterrows(), start=1):
        title = row.get("Заголовок статьи", "") or "Без заголовка"
        url = row.get("Ссылка на источник", "") or "-"
        source_name = row.get("Источник", "") or "unknown"
        pub_date = row.get("Дата новости", "")
        keywords = row.get("Ключевые слова", [])
        score = row.get("llm_score", "")
        summary = row.get("llm_summary", "")

        if pd.notna(pub_date):
            if hasattr(pub_date, "strftime"):
                pub_date = pub_date.strftime("%d.%m.%Y %H:%M")
            else:
                pub_date = str(pub_date)
        else:
            pub_date = "-"

        if isinstance(keywords, list):
            keywords_str = ", ".join(str(x) for x in keywords if str(x).strip())
        elif keywords is None:
            keywords_str = "-"
        else:
            keywords_str = str(keywords).strip() or "-"

        lines.append(f"{idx}. {title}")
        lines.append(f"   Источник: {source_name}")
        lines.append(f"   Дата: {pub_date}")
        lines.append(f"   llm_score: {score}")
        lines.append(f"   Кратко: {_safe_str(summary) or '-'}")
        lines.append(f"   Ключевые слова: {keywords_str}")
        lines.append(f"   Ссылка: {url}")
        lines.append("")

    lines.append("Есть вопросы/предложения? Отправьте на почту GAZelenskiy@sberbank.ru")

    return "\n".join(lines)


def prepare_send_news(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    require_llm_columns_for_send(df)

    if df is None or df.empty:
        return pd.DataFrame(columns=DEFAULT_REQUIRED_COLUMNS)

    work_df = df.copy()

    for col in DEFAULT_REQUIRED_COLUMNS:
        if col not in work_df.columns:
            work_df[col] = None

    work_df["llm_score"] = pd.to_numeric(work_df["llm_score"], errors="coerce")
    work_df = work_df.sort_values("llm_score", ascending=False)
    work_df = work_df.head(limit).reset_index(drop=True)

    return work_df[DEFAULT_REQUIRED_COLUMNS]


def format_keywords_html(keywords_value) -> str:
    keywords = _normalize_keywords(keywords_value)

    if not keywords:
        return '<span style="font-size:12px;line-height:18px;color:#9ca3af;">—</span>'

    badges = []
    for kw in keywords:
        badges.append(
            f"""
            <span style="
                display:inline-block;
                background:#eef4ff;
                color:#005ff9;
                border:1px solid #d7e6ff;
                border-radius:999px;
                padding:6px 10px;
                font-size:12px;
                line-height:16px;
                margin:0 0 8px 8px;
                font-weight:700;
                white-space:normal;
            ">{kw}</span>
            """
        )

    return "".join(badges)


def build_news_cards_html(news_df: pd.DataFrame) -> str:
    if news_df.empty:
        return """
        <tr>
            <td style="padding:0 0 16px 0;">
                <table width="100%" cellpadding="0" cellspacing="0" border="0"
                       style="background:#ffffff;border:1px solid #e8e8e8;border-radius:16px;">
                    <tr>
                        <td style="padding:24px;">
                            <div style="font-size:16px;line-height:24px;color:#374151;">
                                Новостей для отображения не найдено.
                            </div>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
        """

    cards = []

    for _, row in news_df.iterrows():
        title = _safe_str(row.get("Заголовок статьи")) or "Без заголовка"
        url = _safe_str(row.get("Ссылка на источник")) or "#"
        source_name = _safe_str(row.get("Источник")) or "unknown"
        summary = _safe_str(row.get("llm_summary")) or "—"
        pub_date = row.get("Дата новости")

        if pd.notna(pub_date):
            if hasattr(pub_date, "strftime"):
                pub_date_str = pub_date.strftime("%d.%m.%Y")
            else:
                pub_date_str = _safe_str(pub_date)
        else:
            pub_date_str = ""

        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        if domain.startswith("www."):
            domain = domain[4:]

        meta_line = source_name
        if pub_date_str:
            meta_line = f"{domain or source_name} • {pub_date_str}"

        cards.append(
            f"""
            <tr>
                <td style="padding:0 0 16px 0;">
                    <table width="100%" cellpadding="0" cellspacing="0" border="0"
                           style="background:#ffffff;border:1px solid #e7ebf0;border-radius:18px;">
                        <tr>
                            <td width="70%" valign="top" style="padding:22px;">
                                <div style="font-size:12px;line-height:18px;color:#6b7280;margin-bottom:8px;">
                                    {meta_line}
                                </div>

                                <div style="font-size:18px;line-height:26px;font-weight:700;color:#111827;margin-bottom:16px;">
                                    {title}
                                </div>
                                <div style="font-size:14px;line-height:20px;font-weight:400;color:#4b5563;">
                                    {summary}
                                </div>

                                <a href="{url}"
                                   target="_blank"
                                   style="
                                       display:inline-block;
                                       background:#005ff9;
                                       color:#ffffff;
                                       text-decoration:none;
                                       font-size:14px;
                                       line-height:20px;
                                       font-weight:700;
                                       padding:10px 18px;
                                       border-radius:10px;
                                   ">
                                    Читать
                                </a>
                            </td>

                            <td width="30%" valign="top" align="right"
                                style="padding:22px;text-align:right;border-left:1px solid #f1f5f9;">
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            """
        )

    return "\n".join(cards)


def build_html_report(
    news_df: pd.DataFrame,
    total_count: int,
    header_cid: str,
    title: str = "Новостной дайджест",
    subtitle: str = "Топ новостей по llm_score",
) -> str:
    news_cards_html = build_news_cards_html(news_df)

    return f"""
    <html>
      <body style="margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#111827;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f3f6fb;padding:24px 0;">
          <tr>
            <td align="center">

              <table width="760" cellpadding="0" cellspacing="0" border="0"
                     style="width:760px;max-width:760px;background:#f3f6fb;">

                <tr>
                  <td style="padding:0 0 20px 0;">
                    <img src="cid:{header_cid}"
                         alt="header"
                         width="760"
                         style="display:block;width:100%;max-width:760px;height:auto;border-radius:22px;">
                  </td>
                </tr>

                <tr>
                  <td style="background:#ffffff;border-radius:22px;padding:28px 32px;">
                    <div style="font-size:30px;line-height:38px;font-weight:700;color:#111827;margin-bottom:10px;">
                      {title}
                    </div>

                    <div style="font-size:16px;line-height:24px;color:#4b5563;margin-bottom:18px;">
                      {subtitle}
                    </div>

                    <div style="
                        display:inline-block;
                        background:#eef4ff;
                        color:#005ff9;
                        font-size:14px;
                        line-height:20px;
                        font-weight:700;
                        padding:10px 14px;
                        border-radius:12px;
                    ">
                      Всего найдено новостей: {total_count}
                    </div>
                  </td>
                </tr>

                <tr><td style="height:20px;"></td></tr>

                {news_cards_html}

                <tr>
                  <td style="padding-top:8px;">
                    <div style="font-size:12px;line-height:18px;color:#6b7280;text-align:center;padding:12px 0;">
                      Письмо сформировано автоматически системой мониторинга новостей.
                      "Есть вопросы/предложения? Отправьте на почту GAZelenskiy@sberbank.ru"
                    </div>
                  </td>
                </tr>

              </table>

            </td>
          </tr>
        </table>
      </body>
    </html>
    """


def attach_inline_image(msg: EmailMessage, image_path: str | Path, cid: str) -> None:
    path = Path(image_path)

    if not path.exists():
        raise FileNotFoundError(f"Файл изображения не найден: {path}")

    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type:
        maintype, subtype = mime_type.split("/", 1)
    else:
        maintype, subtype = "image", "png"

    with open(path, "rb") as f:
        img_data = f.read()

    html_part = msg.get_payload()[-1]
    html_part.add_related(
        img_data,
        maintype=maintype,
        subtype=subtype,
        cid=f"<{cid}>",
        filename=path.name,
    )


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


def send_news_email(
    smtp_login: str,
    smtp_password: str,
    recipients: list[str],
    subject: str,
    final_df: pd.DataFrame,
    header_image_path: str | Path | None = None,
    smtp_host: str = "smtp.mail.ru",
    smtp_port: int = 465,
    latest_news_limit: int = 10,
    attachments: list[str] | None = None,
    report_title: str = "Новостной дайджест",
    report_subtitle: str = "Топ новостей по llm_score",
) -> None:
    if not recipients:
        raise ValueError("Список recipients пуст")

    require_llm_columns_for_send(final_df)
    top_news_df = prepare_send_news(final_df, limit=latest_news_limit)
    total_count = 0 if final_df is None else len(final_df)
    header_path = resolve_email_header_path(header_image_path)

    header_cid = make_msgid(domain="mail").strip("<>")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_login
    msg["To"] = ", ".join(recipients)

    msg.set_content(
        f"Найдено новостей: {total_count}. "
        f"Откройте письмо в HTML-режиме для просмотра отчета."
    )

    html_content = build_html_report(
        news_df=top_news_df,
        total_count=total_count,
        header_cid=header_cid,
        title=report_title,
        subtitle=report_subtitle,
    )
    msg.add_alternative(html_content, subtype="html")

    attach_inline_image(msg, header_path, header_cid)

    if attachments:
        attach_files(msg, attachments)

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(smtp_login, smtp_password)
        server.send_message(msg)


def send_news_email_plain(
    smtp_login: str,
    smtp_password: str,
    recipients: list[str],
    subject: str,
    final_df: pd.DataFrame,
    smtp_host: str = "smtp.mail.ru",
    smtp_port: int = 465,
    latest_news_limit: int = 10,
    attachments: list[str] | None = None,
) -> None:
    if not recipients:
        raise ValueError("Список recipients пуст")

    require_llm_columns_for_send(final_df)
    top_news_df = prepare_send_news(final_df, limit=latest_news_limit)
    total_count = 0 if final_df is None else len(final_df)

    text_content = build_plain_text_report(
        news_df=top_news_df,
        total_count=total_count,
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_login
    msg["To"] = ", ".join(recipients)
    msg.set_content(text_content)

    if attachments:
        attach_files(msg, attachments)

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(smtp_login, smtp_password)
        server.send_message(msg)
