import os

from common.paths import PROJECT_ROOT
from config.ck import CK_BY_ID, discover_ck_profiles, normalize_ck_id
from config.sources.registry import (
    SOURCES,
    SOURCES_BY_ID,
    get_cache_date_key_format,
    get_cache_root_key,
    get_source_label,
    source_choices,
    source_ids,
)


def test_registry_has_ten_sources():
    assert len(SOURCES) == 10
    assert len(SOURCES_BY_ID) == 10


def test_registry_source_order_is_unique():
    orders = [spec.order for spec in SOURCES]
    assert len(orders) == len(set(orders))


def test_registry_only_kommersant_is_lazy():
    lazy_sources = [spec.id for spec in SOURCES if spec.lazy]
    assert lazy_sources == ["kommersant"]


def test_registry_source_ids_match_choices():
    assert source_choices() == sorted(source_ids())


def test_registry_labels_are_non_empty():
    for source_id in source_ids():
        assert get_source_label(source_id)


def test_registry_cache_root_keys():
    assert get_cache_root_key("consultant") == "reviews"
    assert get_cache_root_key("banki") == "days"
    assert get_cache_root_key("kommersant") == "days"


def test_registry_cache_date_formats():
    assert get_cache_date_key_format("interfax") == "%Y/%m/%d"
    assert get_cache_date_key_format("kommersant") == "%Y-%m-%d"
    assert get_cache_date_key_format("banki") is None


def test_registry_parser_specs_are_complete():
    for spec in SOURCES:
        assert spec.parser_module.startswith("parsers.")
        assert spec.parser_class


def test_registry_parser_modules_exist_on_disk():
    for spec in SOURCES:
        module_path = os.path.join(PROJECT_ROOT, *spec.parser_module.split(".")) + ".py"
        assert os.path.isfile(module_path), module_path


def test_registry_lazy_parser_is_kommersant():
    spec = SOURCES_BY_ID["kommersant"]
    assert spec.lazy is True
    assert spec.parser_module == "parsers.kommersant.parser"
    assert spec.parser_class == "KommersantParser"


def test_ck_registry_aliases():
    assert normalize_ck_id("ПС") == "payment_systems"
    assert normalize_ck_id("ЦК ССЭМ") == "ssem"
    assert normalize_ck_id("Налоги") == "taxes"
    assert normalize_ck_id("unknown") == "unknown"


def test_discovered_ck_profiles_match_registry():
    discovered = discover_ck_profiles()
    assert discovered
    for ck_id in CK_BY_ID:
        assert ck_id in discovered
