import re
from dataclasses import dataclass
from importlib import import_module


@dataclass
class FilterProfile:
    name: str
    title: str
    core_rules: list
    secondary_rules: list
    exclude_rules: list
    payment_context: str = ""
    require_core_match: bool = False


class CompiledFilter:
    def __init__(self, profile: FilterProfile):
        self.profile = profile
        self._compiled_core = self._compile_rules(profile.core_rules)
        self._compiled_secondary = self._compile_rules(profile.secondary_rules)
        self._compiled_exclude = self._compile_rules(profile.exclude_rules)
        self._payment_context = re.compile(
            r"(?:"
            + profile.payment_context
            + r")",
            re.IGNORECASE | re.UNICODE,
        )

    @staticmethod
    def _compile_rules(rules):
        return [
            (label, re.compile(pattern, re.IGNORECASE | re.UNICODE))
            for label, pattern in rules
        ]

    def _has_payment_context(self, text):
        return self._payment_context.search(text) is not None

    def find_core_matches(self, text):
        if not text:
            return []

        matches = []

        for label, pattern in self._compiled_core:
            match = pattern.search(text)
            if match:
                matches.append((label, match.group(0)))

        return matches

    def find_keyword_matches(self, text):
        if not text:
            return []

        matches = list(self.find_core_matches(text))

        if self._has_payment_context(text):
            for label, pattern in self._compiled_secondary:
                match = pattern.search(text)
                if match:
                    matches.append((label, match.group(0)))

        return matches

    def find_exclusion_matches(self, text):
        if not text:
            return []

        matches = []

        for label, pattern in self._compiled_exclude:
            match = pattern.search(text)
            if match:
                matches.append((label, match.group(0)))

        return matches

    def format_matched_keywords(self, text):
        matches = self.find_keyword_matches(text)

        if not matches:
            return ""

        parts = []
        seen = set()

        for label, fragment in matches:
            key = (label, fragment)
            if key in seen:
                continue

            seen.add(key)
            parts.append(f"{label}: «{fragment}»")

        return "; ".join(parts)

    def matches_keywords(self, text):
        if not text:
            return False

        if self.find_exclusion_matches(text):
            return False

        if self.profile.require_core_match:
            return bool(self.find_core_matches(text))

        return bool(self.find_keyword_matches(text))


def compile_profile(profile: FilterProfile) -> CompiledFilter:
    return CompiledFilter(profile)


def load_filter(ck_id: str) -> CompiledFilter:
    module = import_module(f"filters.ck.{ck_id}.rules")
    return compile_profile(module.PROFILE)
