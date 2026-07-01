from llm.ranking_prompts.payment_systems import PAYMENT_SYSTEMS_PROFILE
from llm.ranking_prompts.ssem import SSEM_PROFILE
from llm.ranking_prompts.taxes import TAXES_PROFILE


CK_NAME_TO_ID = {
    "ПС": "payment_systems",
    "ЦК по платежным системам": "payment_systems",
    "ССЭМ": "ssem",
    "ЦК ССЭМ": "ssem",
    "Налоги": "taxes",
    "ЦК по налогам": "taxes",
}

PROFILES = {
    "payment_systems": PAYMENT_SYSTEMS_PROFILE,
    "ssem": SSEM_PROFILE,
    "taxes": TAXES_PROFILE,
}


def normalize_ck_id(ck_name):
    value = str(ck_name or "").strip()
    return CK_NAME_TO_ID.get(value, value)


def get_profile(ck_name):
    ck_id = normalize_ck_id(ck_name)
    return PROFILES.get(ck_id)
