from __future__ import annotations

import os
from dataclasses import dataclass

from common.paths import PROJECT_ROOT


@dataclass(frozen=True)
class CKSpec:
    id: str
    export_title: str
    aliases: tuple[str, ...]


CK_SPECS: tuple[CKSpec, ...] = (
    CKSpec(
        "payment_systems",
        "ПС",
        ("ПС", "ЦК по платежным системам"),
    ),
    CKSpec(
        "ssem",
        "ССЭМ",
        ("ССЭМ", "ЦК ССЭМ"),
    ),
    CKSpec(
        "taxes",
        "Налоги",
        ("Налоги", "ЦК по налогам"),
    ),
)

CK_BY_ID = {spec.id: spec for spec in CK_SPECS}

CK_NAME_TO_ID: dict[str, str] = {}
for spec in CK_SPECS:
    CK_NAME_TO_ID[spec.id] = spec.id
    for alias in spec.aliases:
        CK_NAME_TO_ID[alias] = spec.id


def ck_ids() -> list[str]:
    return [spec.id for spec in CK_SPECS]


def normalize_ck_id(ck_name) -> str:
    value = str(ck_name or "").strip()
    return CK_NAME_TO_ID.get(value, value)


def get_ck_export_title(ck_id: str) -> str | None:
    spec = CK_BY_ID.get(ck_id)
    if spec is None:
        return None
    return spec.export_title


def discover_ck_profiles() -> list[str]:
    ck_root = os.path.join(PROJECT_ROOT, "filters", "ck")
    profiles = []

    for name in sorted(os.listdir(ck_root)):
        if name.startswith("__"):
            continue

        rules_path = os.path.join(ck_root, name, "rules.py")
        if os.path.isfile(rules_path):
            profiles.append(name)

    return profiles
