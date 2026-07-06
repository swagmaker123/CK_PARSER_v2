import pytest

from mailer import require_llm_columns_for_send


class _FakeDataFrame:
    def __init__(self, columns):
        self.columns = columns


def test_require_llm_columns_passes_when_present():
    require_llm_columns_for_send(_FakeDataFrame(["llm_score", "llm_summary"]))


def test_require_llm_columns_exits_when_missing():
    with pytest.raises(SystemExit, match="llm_score"):
        require_llm_columns_for_send(
            _FakeDataFrame(["Заголовок статьи"]),
            "output/news_test.xlsx",
        )


def test_resolve_email_header_path_exits_when_missing():
    from mailer import resolve_email_header_path

    with pytest.raises(SystemExit, match="email_header"):
        resolve_email_header_path("assets/__missing_header__.png")
