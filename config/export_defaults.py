import json
import os

from common.paths import PROJECT_ROOT


def load_export_config(source_id=None, ck_id=None):
    config_path = os.path.join(PROJECT_ROOT, "export", "default.json")

    with open(config_path, encoding="utf-8") as f:
        return json.load(f)
