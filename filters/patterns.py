"""Общие regex-паттерны для фильтров ЦК (границы кириллических слов)."""

WB_L = r"(?<![а-яё])"
WB_R = r"(?![а-яё])"


def acro(pattern):
    return rf"{WB_L}(?:{pattern}){WB_R}"


def word(stem):
    return rf"{WB_L}{stem}{WB_R}"
