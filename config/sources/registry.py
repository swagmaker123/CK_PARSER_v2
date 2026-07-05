from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class SourceSpec:
    id: str
    label: str
    parser_module: str
    parser_class: str
    cache_root_key: str = "days"
    cache_date_key_format: str | None = None
    order: int = 0
    lazy: bool = False


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec("banki", "Банки.ру", "parsers.banki.parser", "BankiParser", order=10),
    SourceSpec("cbr", "Центробанк", "parsers.cbr.parser", "CbrParser", order=20),
    SourceSpec("garant", "Гарант.ру", "parsers.garant.parser", "GarantParser", order=30),
    SourceSpec(
        "interfax",
        "Interfax",
        "parsers.interfax.parser",
        "InterfaxParser",
        cache_date_key_format="%Y/%m/%d",
        order=40,
    ),
    SourceSpec(
        "kommersant",
        "Kommersant",
        "parsers.kommersant.parser",
        "KommersantParser",
        cache_date_key_format="%Y-%m-%d",
        order=50,
        lazy=True,
    ),
    SourceSpec("minfin", "МинФин", "parsers.minfin.parser", "MinfinParser", order=60),
    SourceSpec("nalog", "ФНС", "parsers.nalog.parser", "NalogParser", order=70),
    SourceSpec("palata", "Палата НК", "parsers.palata.parser", "PalataParser", order=80),
    SourceSpec("rbc", "РБК", "parsers.rbc.parser", "RbcParser", order=90),
    SourceSpec(
        "consultant",
        "Consultant",
        "parsers.consultant.parser",
        "ConsultantParser",
        cache_root_key="reviews",
        order=100,
    ),
)

SOURCES_BY_ID = {spec.id: spec for spec in SOURCES}


def source_ids() -> list[str]:
    return [spec.id for spec in sorted(SOURCES, key=lambda item: item.order)]


def source_choices() -> list[str]:
    return sorted(SOURCES_BY_ID)


def get_source_spec(source_id: str) -> SourceSpec:
    try:
        return SOURCES_BY_ID[source_id]
    except KeyError as exc:
        raise KeyError(f"Неизвестный источник: {source_id}") from exc


def get_source_label(source_id: str) -> str:
    return get_source_spec(source_id).label


def get_cache_root_key(source_id: str) -> str:
    return get_source_spec(source_id).cache_root_key


def get_cache_date_key_format(source_id: str) -> str | None:
    return get_source_spec(source_id).cache_date_key_format


def get_parser_class(source_id: str):
    spec = get_source_spec(source_id)
    module = import_module(spec.parser_module)
    return getattr(module, spec.parser_class)
