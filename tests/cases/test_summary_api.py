"""AC4 for specs/case-summary.md: `summarize`, the generator registry and the narrative contract."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from aml.cases.runner import CaseError
from aml.common.db import DuckDb

from .helpers import CASE_C01_A, duck_settings, load_case
from .summary_helpers import (
    V1_CITATIONS,
    WATERMARK,
    install_dummy,
    mini_n,
    narrative,
    render_summary,
    summarize,
    table_counts,
    two_runs,
)


@pytest.fixture(scope="module")
def mn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[DuckDb]:
    """MINI-N after run 1; `summarize` never writes, so the tests share it."""
    db = DuckDb(tmp_path_factory.mktemp("summary_api") / "mn.duckdb")
    mini_n(db)
    yield db
    db.close()


def test_ac4_summarize_returns_the_template_narrative(mn: DuckDb) -> None:
    n = summarize(mn, duck_settings(), CASE_C01_A)
    assert n.case_id == "C-C01-20260302"
    assert n.generator == "template"
    assert n.version == "summary/v1"
    assert n.language == "en"
    assert n.watermark == WATERMARK
    assert n.markdown == render_summary(load_case(mn, CASE_C01_A))
    assert n.citations == V1_CITATIONS


def test_ac4_summarize_writes_nothing(mn: DuckDb) -> None:
    settings = duck_settings()
    before = table_counts(mn)
    summarize(mn, settings, CASE_C01_A)
    summarize(mn, settings, CASE_C01_A)
    for call in (
        lambda: summarize(mn, settings, CASE_C01_A, language="vi"),
        lambda: summarize(mn, settings, "C-NOPE-20260101"),
        lambda: summarize(mn, settings, CASE_C01_A, generator="llm"),
    ):
        with pytest.raises(Exception):  # noqa: B017 - the failures are checked in other tests
            call()
    assert table_counts(mn) == before


def test_ac4_other_language_is_refused(mn: DuckDb) -> None:
    with pytest.raises(narrative().NarrativeError) as err:
        summarize(mn, duck_settings(), CASE_C01_A, language="vi")
    assert "language 'vi' is not available in the template generator" in str(err.value)


def test_ac4_unknown_case_raises_case_error(mn: DuckDb) -> None:
    with pytest.raises(CaseError) as err:
        summarize(mn, duck_settings(), "C-NOPE-20260101")
    assert "unknown case_id" in str(err.value)


def test_ac4_unknown_generator_name(mn: DuckDb) -> None:
    with pytest.raises(narrative().NarrativeError) as err:
        summarize(mn, duck_settings(), CASE_C01_A, generator="llm")
    assert "unknown narrative generator 'llm'" in str(err.value)


def test_ac4_registered_generator_is_used_by_name(mn: DuckDb) -> None:
    install_dummy()
    n = summarize(mn, duck_settings(), CASE_C01_A, generator="dummy")
    assert n.markdown == "DRAFT-X\nhello"
    assert n.generator == "dummy"


def test_ac4_generator_comes_from_the_setting_when_not_passed(mn: DuckDb) -> None:
    install_dummy()
    settings = duck_settings(AML__CASES__SUMMARY__GENERATOR="dummy")
    assert summarize(mn, settings, CASE_C01_A).markdown == "DRAFT-X\nhello"


def test_ac4_contract_needs_the_watermark_in_the_markdown(mn: DuckDb) -> None:
    install_dummy(markdown="hello")
    with pytest.raises(narrative().NarrativeError) as err:
        summarize(mn, duck_settings(), CASE_C01_A, generator="dummy")
    assert "narrative contract violated" in str(err.value)


def test_ac4_contract_needs_the_same_case_id(mn: DuckDb) -> None:
    install_dummy(case_id="C-OTHER-20260101")
    with pytest.raises(narrative().NarrativeError) as err:
        summarize(mn, duck_settings(), CASE_C01_A, generator="dummy")
    assert "narrative contract violated" in str(err.value)


def test_ac4_contract_needs_a_non_empty_watermark_and_markdown(mn: DuckDb) -> None:
    for kwargs in ({"watermark": ""}, {"markdown": "", "watermark": "DRAFT-X"}):
        install_dummy(**kwargs)
        with pytest.raises(narrative().NarrativeError) as err:
            summarize(mn, duck_settings(), CASE_C01_A, generator="dummy")
        assert "narrative contract violated" in str(err.value), kwargs


def test_ac4_generator_receives_a_masked_case_view(mn: DuckDb) -> None:
    seen = install_dummy()
    summarize(mn, duck_settings(), CASE_C01_A, generator="dummy")
    assert len(seen) == 1
    case = seen[0]
    assert type(case).__name__ == "CaseView"
    assert case.case_id == CASE_C01_A
    assert case.subjects
    assert "dob" not in case.subjects[0]
    assert case.subjects[0]["full_name"] == "Nguyễn V. A."


def test_ac4_run_id_selects_the_snapshot(tmp_path_factory: pytest.TempPathFactory) -> None:
    db = DuckDb(tmp_path_factory.mktemp("summary_api2") / "mn2.duckdb")
    try:
        settings = two_runs(db)
        latest = summarize(db, settings, CASE_C01_A)
        first = summarize(db, settings, CASE_C01_A, run_id=1)
        assert (
            latest.markdown.splitlines()[-1] == "Template summary/v1; case run 2; no LLM was used."
        )
        assert (
            first.markdown.splitlines()[-1] == "Template summary/v1; case run 1; no LLM was used."
        )
        assert first.markdown == render_summary(load_case(db, CASE_C01_A, run_id=1))
        assert "- Status: OPEN" in first.markdown.splitlines()
        assert "- Status: CLOSED" in latest.markdown.splitlines()
    finally:
        db.close()
