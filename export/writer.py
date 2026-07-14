import re
from datetime import date, datetime

import pandas as pd

from config.ck import get_ck_export_title
from config.sources.registry import get_source_label

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
    from config.export_defaults import load_export_config as _load_export_config

    return _load_export_config(source_id, ck_id)


def get_ck_title(ck_id):
    export_title = get_ck_export_title(ck_id)
    if export_title:
        return export_title

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
            row[column] = get_source_label(source_id)
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
    """
    Дописывает новости в активный Excel-период (append по URL+ЦК).

    Имя файла: news_FROM_TO.xlsx. После send период закрывается
    (см. export.workbook.archive_after_send).
    """
    from export.workbook import (
        get_active_path,
        merge_workbooks,
        rename_active_workbook,
        resolve_period_bounds,
        set_active_path,
        target_path_for_bounds,
        write_df_atomic,
        ensure_output_dirs,
    )

    if run_date is None:
        run_date = datetime.now().strftime("%Y-%m-%d")

    ensure_output_dirs()

    rows = []
    for ck_id, source_data in combined_by_ck.items():
        for source_id, articles in source_data.items():
            for item in articles or []:
                rows.append(_project_row(item, ck_id, source_id))

    new_df = pd.DataFrame(rows, columns=UNIFIED_COLUMNS)

    active = get_active_path()
    existing_df = None
    if active is not None and active.is_file():
        try:
            existing_df = pd.read_excel(active)
        except Exception:
            existing_df = None

    merged = merge_workbooks(existing_df, new_df)
    date_from, date_to = resolve_period_bounds(active, merged, run_date)
    target = target_path_for_bounds(date_from, date_to)

    if active is None:
        write_df_atomic(target, merged)
        set_active_path(target)
        return str(target)

    if active.resolve() == target.resolve():
        write_df_atomic(target, merged)
        set_active_path(target)
        return str(target)

    # Сначала пишем во временное имя рядом, потом atomic rename периода
    write_df_atomic(active, merged)
    return str(rename_active_workbook(active, target))
