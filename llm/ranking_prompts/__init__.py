from llm.ranking_prompts.payment_systems import PAYMENT_SYSTEMS_PROFILE
from llm.ranking_prompts.ssem import SSEM_PROFILE
from llm.ranking_prompts.taxes import TAXES_PROFILE
from config.ck import normalize_ck_id as _normalize_ck_id


PROFILES = {
    "payment_systems": PAYMENT_SYSTEMS_PROFILE,
    "ssem": SSEM_PROFILE,
    "taxes": TAXES_PROFILE,
}


def normalize_ck_id(ck_name):
    return _normalize_ck_id(ck_name)


def get_profile(ck_name):
    ck_id = normalize_ck_id(ck_name)
    return PROFILES.get(ck_id)
