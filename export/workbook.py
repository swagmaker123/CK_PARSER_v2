"""Активный Excel на период: маркер, имя news_FROM_TO, архив после send."""

from __future__ import annotations

import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from common.paths import PROJECT_ROOT

OUTPUT_DIR = Path(PROJECT_ROOT) / "output"
SENT_DIR = OUTPUT_DIR / "sent"
ACTIVE_MARKER = OUTPUT_DIR / ".active_workbook"

NEWS_RANGE_RE = re.compile(
    r"^news_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.xlsx$",
    re.IGNORECASE,
)

URL_COLUMN = "Ссылка на источник"
CK_COLUMN = "Наименование ЦК"
DATE_COLUMN = "Дата новости"


def ensure_output_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SENT_DIR.mkdir(parents=True, exist_ok=True)


def workbook_name(date_from: str, date_to: str) -> str:
    return f"news_{date_from}_{date_to}.xlsx"


def parse_range_from_name(path: str | Path) -> tuple[str, str] | None:
    match = NEWS_RANGE_RE.match(Path(path).name)
    if not match:
        return None
    return match.group(1), match.group(2)


def normalize_url(value) -> str:
    return str(value or "").strip().rstrip("/")


def row_dedupe_key(row: pd.Series) -> tuple[str, str]:
    return (
        normalize_url(row.get(URL_COLUMN, "")),
        str(row.get(CK_COLUMN, "") or "").strip(),
    )


def get_active_path() -> Path | None:
    """Путь к активному workbook или None, если периода нет / файл пропал."""
    if not ACTIVE_MARKER.is_file():
        return None

    raw = ACTIVE_MARKER.read_text(encoding="utf-8").strip()
    if not raw:
        return None

    path = Path(raw)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()

    if not path.is_file():
        clear_active_path()
        return None
    return path


def set_active_path(path: str | Path) -> Path:
    ensure_output_dirs()
    path = Path(path).resolve()
    try:
        rel = path.relative_to(Path(PROJECT_ROOT).resolve())
        stored = rel.as_posix()
    except ValueError:
        stored = str(path)
    ACTIVE_MARKER.write_text(stored + "\n", encoding="utf-8")
    return path


def clear_active_path() -> None:
    if ACTIVE_MARKER.exists():
        try:
            ACTIVE_MARKER.unlink()
        except OSError:
            ACTIVE_MARKER.write_text("", encoding="utf-8")


def require_active_path() -> Path:
    path = get_active_path()
    if path is None:
        raise FileNotFoundError(
            "Нет активного Excel-периода (output/.active_workbook). "
            "Сначала запустите парсинг / export, либо укажите --output."
        )
    return path


def parse_news_date(value) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text or text.lower() in ("nan", "nat", "none"):
        return None

    match = re.search(r"\b(\d{1,2})[.](\d{1,2})[.](\d{4})\b", text)
    if match:
        day, month, year = match.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            return None

    match = re.search(r"(?<!\d)(\d{4})[-/](\d{2})[-/](\d{2})(?!\d)", text)
    if match:
        year, month, day = match.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            return None

    return None


def max_news_date_iso(df: pd.DataFrame, fallback: str) -> str:
    if df is None or df.empty or DATE_COLUMN not in df.columns:
        return fallback

    dates = []
    for value in df[DATE_COLUMN]:
        parsed = parse_news_date(value)
        if parsed is not None:
            dates.append(parsed)
    if not dates:
        return fallback
    return max(dates).strftime("%Y-%m-%d")


def resolve_period_bounds(
    existing_path: Path | None,
    merged_df: pd.DataFrame,
    run_date: str,
) -> tuple[str, str]:
    """FROM = начало периода (из имени или run_date); TO = max дата новости."""
    date_from = run_date
    if existing_path is not None:
        parsed = parse_range_from_name(existing_path)
        if parsed:
            date_from = parsed[0]
        elif existing_path.is_file():
            # Старый news_YYYY-MM-DD.xlsx — берём дату из имени как FROM
            stem = existing_path.stem
            m = re.match(r"^news_(\d{4}-\d{2}-\d{2})$", stem)
            if m:
                date_from = m.group(1)

    date_to = max_news_date_iso(merged_df, fallback=run_date)
    if date_to < date_from:
        date_to = date_from
    return date_from, date_to


def target_path_for_bounds(date_from: str, date_to: str) -> Path:
    ensure_output_dirs()
    return OUTPUT_DIR / workbook_name(date_from, date_to)


def merge_workbooks(existing_df: pd.DataFrame | None, new_df: pd.DataFrame) -> pd.DataFrame:
    """Append-only merge: существующие ключи (URL+ЦК) не перезаписываются."""
    if existing_df is None or existing_df.empty:
        return new_df.copy() if new_df is not None else pd.DataFrame()

    if new_df is None or new_df.empty:
        return existing_df.copy()

    existing = existing_df.copy()
    incoming = new_df.copy()

    existing_keys = {row_dedupe_key(row) for _, row in existing.iterrows()}
    to_add = []
    for _, row in incoming.iterrows():
        key = row_dedupe_key(row)
        if not key[0]:
            # без URL — добавляем всегда (редкий крайний случай)
            to_add.append(row)
            continue
        if key not in existing_keys:
            to_add.append(row)
            existing_keys.add(key)

    if not to_add:
        return existing

    added = pd.DataFrame(to_add)
    # Сохраняем все колонки (llm_* и пр. из existing)
    merged = pd.concat([existing, added], ignore_index=True, sort=False)
    return merged


def write_df_atomic(path: Path, df: pd.DataFrame) -> None:
    ensure_output_dirs()
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        df.to_excel(tmp, index=False, engine="openpyxl")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def rename_active_workbook(old_path: Path, new_path: Path) -> Path:
    old_path = Path(old_path).resolve()
    new_path = Path(new_path).resolve()
    if old_path == new_path:
        return set_active_path(new_path)

    if new_path.exists() and new_path != old_path:
        raise FileExistsError(f"Целевой workbook уже существует: {new_path}")

    os.replace(old_path, new_path)
    return set_active_path(new_path)


def archive_after_send(sent_path: str | Path) -> Path:
    """
    Копирует файл в output/sent/, если это активный — удаляет оригинал
    и сбрасывает маркер периода.
    """
    ensure_output_dirs()
    sent_path = Path(sent_path).resolve()
    if not sent_path.is_file():
        raise FileNotFoundError(f"Нечего архивировать: {sent_path}")

    dest = SENT_DIR / sent_path.name
    if dest.exists():
        stamp = datetime.now().strftime("%H%M%S")
        dest = SENT_DIR / f"{sent_path.stem}_sent_{stamp}{sent_path.suffix}"

    shutil.copy2(sent_path, dest)

    active = get_active_path()
    is_active = active is not None and active.resolve() == sent_path
    if is_active:
        try:
            sent_path.unlink()
        except OSError:
            pass
        clear_active_path()

    return dest
