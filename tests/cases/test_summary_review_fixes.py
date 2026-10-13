"""Review follow-ups for specs/case-summary.md: stable ordering and missing values."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any

import pytest

from aml.common.db import DuckDb

from .summary_helpers import block, mini_n, render_summary, v1


@pytest.fixture(scope="module")
def view(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    with DuckDb(tmp_path_factory.mktemp("summary_fixes") / "mn.duckdb") as db:
        mini_n(db)
        yield v1(db)


def _with(view: Any, section: str, content: dict[str, Any]) -> Any:
    return dataclasses.replace(view, enrichment={**view.enrichment, section: content})


def test_transaction_dq_lines_do_not_depend_on_the_stored_key_order(view: Any) -> None:
    # a JSON column may hand its keys back in another order on another backend
    one = _with(view, "dq_issues", {"customer": [], "transactions": {"TXN_B": 1, "TXN_A": 2}})
    two = _with(view, "dq_issues", {"customer": [], "transactions": {"TXN_A": 2, "TXN_B": 1}})
    assert render_summary(one) == render_summary(two)
    lines = block(render_summary(one), "## Data quality")
    assert [ln for ln in lines if ln.startswith("- transactions")] == [
        "- transactions: TXN_A x 2",
        "- transactions: TXN_B x 1",
    ]


def test_missing_subject_values_print_a_dash_not_none(view: Any) -> None:
    blank = {**view.subjects[0], "kyc_risk": None, "id_type": None, "id_number": None}
    text = render_summary(dataclasses.replace(view, subjects=[blank, *view.subjects[1:]]))
    assert "None" not in text
    assert any(ln.endswith("| - | - - |") for ln in block(text, "## Subject"))


def test_graph_source_with_no_feature_value_says_so(view: Any) -> None:
    network = {**view.enrichment["network"], "source": "gds", "features": {"in_degree": None}}
    text = render_summary(_with(view, "network", network))
    assert "- Graph features (gds): none recorded" in text.splitlines()
