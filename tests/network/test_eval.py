"""AC8 for specs/network-detections.md: `evaluate_network` and `network_coverage` on TINY."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import (
    COVERAGE_COLUMNS,
    COVERAGE_EXPECTED,
    COVERAGE_RULES,
    COVERAGE_VALUE_COLUMNS,
    EVAL_COLUMNS,
    EVAL_EXPECTED,
    EVAL_VALUE_COLUMNS,
    MERCHANT_TINY,
    RULE_IDS,
    TYPOLOGIES,
    cfg,
    duck_settings,
    mod,
    network_error,
    none_if_nan,
    query,
    run_monitoring,
    run_network,
    scalar,
)


def _evaluate(db: DuckDb) -> pd.DataFrame:
    df = mod("aml.graph.network.evaluate").evaluate_network(db)
    df.columns = [c.lower() for c in df.columns]
    return df


def _coverage(db: DuckDb) -> pd.DataFrame:
    df = mod("aml.graph.network.evaluate").network_coverage(db)
    df.columns = [c.lower() for c in df.columns]
    return df


def _assert_row(row: Any, columns: list[str], expected: tuple[Any, ...], label: str) -> None:
    actual = tuple(none_if_nan(getattr(row, c)) for c in columns)
    assert len(actual) == len(expected)
    for column, got, want in zip(columns, actual, expected, strict=True):
        assert got == pytest.approx(want), (label, column, got)


@pytest.fixture
def evaluated(tiny_er: DuckDb) -> DuckDb:
    """TINY after ER, 5a monitoring (31 RULE alerts) and one network run."""
    settings = duck_settings()
    assert run_monitoring(tiny_er, settings).alerts == 31
    assert run_network(tiny_er, settings).alerts == 4
    return tiny_er


def test_ac8_evaluate_network_rows(evaluated: DuckDb) -> None:
    df = _evaluate(evaluated)
    assert list(df.columns) == EVAL_COLUMNS
    assert list(df["rule_id"]) == list(RULE_IDS)
    assert list(df["target_typology"]) == ["mule_ring", "round_tripping", "mule_ring"]
    for row in df.itertuples():
        _assert_row(row, EVAL_VALUE_COLUMNS, EVAL_EXPECTED[row.rule_id], row.rule_id)


def test_ac8_network_coverage_rows(evaluated: DuckDb) -> None:
    df = _coverage(evaluated)
    assert list(df.columns) == COVERAGE_COLUMNS
    assert list(df["typology"]) == TYPOLOGIES
    assert [bool(v) for v in df["is_suspicious"]] == [True] * 4 + [False] * 2
    for row in df.itertuples():
        _assert_row(row, COVERAGE_VALUE_COLUMNS, COVERAGE_EXPECTED[row.typology], row.typology)
        assert (row.rules or "") == COVERAGE_RULES[row.typology], row.typology


def test_ac8_hub_without_inflow_floor_catches_the_benign_merchant(evaluated: DuckDb) -> None:
    run_network(evaluated, cfg(HUBS__MIN_INFLOW_VND="0"))
    df = _evaluate(evaluated).set_index("rule_id")
    hub = df.loc["NET_HUB"]
    expected = (2, 1, 0, 1, 0, 0.5, 0.5, 1, 1, 1.0)
    for column, want in zip(EVAL_VALUE_COLUMNS, expected, strict=True):
        assert none_if_nan(hub[column]) == pytest.approx(want), column

    reason = scalar(
        evaluated,
        "SELECT reason FROM alerts_current WHERE rule_id = 'NET_HUB' "
        f"AND subject_id = '{MERCHANT_TINY}'",
    )
    assert reason.startswith(
        "received 38,925,000 VND from 34 accounts of other customers in 67 transfers"
    )

    coverage = _coverage(evaluated).set_index("typology").loc["benign_merchant"]
    assert int(coverage["flagged_network"]) == 1
    assert int(coverage["accounts_network"]) == 1
    assert coverage["rules"] == "NET_HUB"


def test_ac8_coverage_without_monitoring_has_no_rule_side(tiny_er: DuckDb) -> None:
    run_network(tiny_er, duck_settings())
    df = _coverage(tiny_er)
    assert (df["flagged_rule"] == 0).all()
    assert (df["accounts_rule"] == 0).all()
    mule = df.set_index("typology").loc["mule_ring"]
    assert int(mule["new_by_network"]) == 1
    assert int(mule["accounts_new"]) == 29


def test_ac8_evaluate_before_any_network_run_raises(tiny_er: DuckDb) -> None:
    with pytest.raises(network_error(), match="run `aml network` first"):
        mod("aml.graph.network.evaluate").evaluate_network(tiny_er)
    run_monitoring(tiny_er, duck_settings())  # 5a alerts alone do not count as a NETWORK run
    with pytest.raises(network_error(), match="run `aml network` first"):
        mod("aml.graph.network.evaluate").evaluate_network(tiny_er)
    with pytest.raises(network_error(), match="run `aml network` first"):
        mod("aml.graph.network.evaluate").network_coverage(tiny_er)
    assert not query(tiny_er, "SELECT run_id FROM monitoring_runs").empty
