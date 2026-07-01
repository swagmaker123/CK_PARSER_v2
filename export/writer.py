import json
import os
import re
from datetime import date, datetime

import pandas as pd

from common.paths import PROJECT_ROOT

CK_EXPORT_NAMES = {
    "payment_systems": "ПС",
    "ssem": "ССЭМ",
    "taxes": "Налоги",
}

SOURCE_LABELS = {
    "banki": "Банки.ру",
    "cbr": "Центробанк",
    "garant": "Гарант.ру",
    "interfax": "Interfax",
    "kommersant": "Kommersant",
    "minfin": "МинФин",
    "nalog": "ФНС",
    "palata": "Палата НК",
    "rbc": "РБК",
    "consultant": "Consultant",
}

EXPORT_FIELD_MAP = {
    "Дата новости": "date",
    "Заголовок статьи": "title",
    "Полный текст": "text",
    "Ссылка на источник": "url",
    "Ключевые слова": "matched_keyword",
}

UNIFIED_COLUMNS = [
    "Дата новости",
    "Заголовок статьи",
    "Полный текст",
    "Ссылка на источник",
    "Источник",
    "Наименование ЦК",
    "Ключевые слова",
]

RUSSIAN_MONTHS = {
    "января": "01",
    "февраля": "02",
    "марта": "03",
    "апреля": "04",
    "мая": "05",
    "июня": "06",
    "июля": "07",
    "августа": "08",
    "сентября": "09",
    "октября": "10",
    "ноября": "11",
    "декабря": "12",
}


def load_export_config(source_id=None, ck_id=None):
    config_path = os.path.join(PROJECT_ROOT, "export", "default.json")

    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def get_ck_title(ck_id):
    if ck_id in CK_EXPORT_NAMES:
        return CK_EXPORT_NAMES[ck_id]

    try:
        from filters.engine import load_filter

        profile = load_filter(ck_id).profile
        return profile.title or ck_id
    except (ImportError, AttributeError, ModuleNotFoundError):
        return ck_id


def _format_export_date(value):
    if value is None or value == "":
        return ""

    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")

    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")

    text = str(value).strip()
    if not text:
        return ""

    match = re.search(r"(?<!\d)(\d{4})[-/](\d{2})[-/](\d{2})(?!\d)", text)
    if match:
        year, month, day = match.groups()
        return f"{day}.{month}.{year}"

    match = re.search(r"\b(\d{1,2})[.](\d{1,2})[.](\d{4})\b", text)
    if match:
        day, month, year = match.groups()
        return f"{int(day):02d}.{int(month):02d}.{year}"

    match = re.search(
        r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})\b",
        text.lower(),
        re.IGNORECASE,
    )
    if match:
        day, month_name, year = match.groups()
        month = RUSSIAN_MONTHS.get(month_name)
        if month:
            return f"{int(day):02d}.{month}.{year}"

    return text


def _project_row(item, ck_id, source_id):
    row = {}

    for column in UNIFIED_COLUMNS:
        if column == "Наименование ЦК":
            row[column] = get_ck_title(ck_id)
        elif column == "Источник":
            row[column] = SOURCE_LABELS.get(source_id, source_id)
        else:
            source_field = EXPORT_FIELD_MAP.get(column, column)
            value = item.get(source_field, "")
            row[column] = (
                _format_export_date(value)
                if source_field == "date"
                else value
            )

    return row


def write_unified_excel(combined_by_ck, run_date=None):
    if run_date is None:
        run_date = datetime.now().strftime("%Y-%m-%d")

    output_dir = os.path.join(PROJECT_ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)

    path = os.path.join(output_dir, f"news_{run_date}.xlsx")
    rows = []

    for ck_id, source_data in combined_by_ck.items():
        for source_id, articles in source_data.items():
            for item in articles or []:
                rows.append(_project_row(item, ck_id, source_id))

    df = pd.DataFrame(rows, columns=UNIFIED_COLUMNS)
    df.to_excel(path, index=False, engine="openpyxl")

    return path
