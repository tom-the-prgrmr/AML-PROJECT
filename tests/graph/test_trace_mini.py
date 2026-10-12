"""AC2, AC3, AC4, AC7, AC8 for specs/fund-flow-trace.md: `trace` on the 14-transaction MINI."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import pytest

from aml.common.config import Settings, load_settings
from aml.common.db import DuckDb

from .helpers import (
    AC2_PATHS,
    AC2_ROWS,
    PATH_COLUMNS,
    graph_audit,
    mod,
    path_set,
    rows_of,
    scalar,
    trace,
)


def _raw(mini: DuckDb, settings: Settings, **kw: Any) -> Any:
    kw.setdefault("hops", 4)
    kw.setdefault("hours", 24)
    return trace(mini, settings, "A", method="cte_raw", **kw)


def _edge(mini: DuckDb, settings: Settings, **kw: Any) -> Any:
    return trace(mini, settings, "A", method="cte_edge", hops=4, hours=24, **kw)


# ----------------------------------------------------------------------------- AC2
def test_ac2_cte_raw_mini_rows(mini: DuckDb, settings: Settings) -> None:
    result = _raw(mini, settings)
    paths = result.paths
    assert list(paths.columns) == PATH_COLUMNS
    assert rows_of(paths) == AC2_ROWS
    assert str(paths["hop"].dtype) == "int64"
    assert str(paths["amount_vnd"].dtype) == "int64"
    assert str(paths["is_cycle"].dtype) == "bool"
    assert result.method == "cte_raw"
    assert result.backend == "duckdb"
    assert result.n_paths == 9
    assert result.n_cycles == 3
    assert result.n_accounts == 6
    assert result.query_lines > 0


def test_ac2_cycle_rows_are_not_extended(mini: DuckDb, settings: Settings) -> None:
    found = path_set(_raw(mini, settings))
    for prefix in ("A>A>", "A>B>C>A>", "A>B>C>B>"):
        assert not any(p.startswith(prefix) for p in found), prefix


def test_ac2_chronology_is_strict(mini: DuckDb, settings: Settings) -> None:
    found = path_set(_raw(mini, settings))
    assert "A>B>E" not in found  # M02 happens before M03
    assert "A>B>H" not in found  # M04 has the same second as M03


def test_ac2_first_and_last_ts(mini: DuckDb, settings: Settings) -> None:
    paths = _raw(mini, settings).paths
    row = paths[paths["path"] == "A>B>C>D>F"].iloc[0]
    assert pd.Timestamp(row["first_ts"]) == pd.Timestamp("2026-03-01 10:00:00")
    assert pd.Timestamp(row["last_ts"]) == pd.Timestamp("2026-03-02 10:00:00")
    assert row["account_id"] == "F"


# ----------------------------------------------------------------------------- AC3
def test_ac3_wider_window_adds_m13(mini: DuckDb, settings: Settings) -> None:
    result = _raw(mini, settings, hours=25)
    extra = (4, "A>B>C>D>G", "M03>M06>M11>M13", 40_000_000, False)
    assert result.n_paths == 10
    assert rows_of(result.paths) == sorted([*AC2_ROWS, extra], key=lambda r: (r[0], r[1], r[2]))


def test_ac3_window_upper_bound_is_inclusive(mini: DuckDb, settings: Settings) -> None:
    found = path_set(_raw(mini, settings, hours=24))
    assert "A>B>C>D>G" not in found  # one second past the boundary
    assert "A>B>C>D>F" in found  # exactly on the boundary


@pytest.mark.parametrize(
    ("hops", "expected"),
    [
        (2, ["A>A", "A>B", "A>B>C"]),
        (1, ["A>A", "A>B"]),
        (6, AC2_PATHS),
    ],
)
def test_ac3_hop_limit(mini: DuckDb, settings: Settings, hops: int, expected: list[str]) -> None:
    result = _raw(mini, settings, hops=hops)
    assert list(result.paths["path"]) == expected


def test_ac3_hops_6_equals_ac2_rows(mini: DuckDb, settings: Settings) -> None:
    assert rows_of(_raw(mini, settings, hops=6).paths) == AC2_ROWS


def test_ac3_since_filters_first_hop(mini: DuckDb, settings: Settings) -> None:
    at = _raw(mini, settings, since=datetime(2026, 3, 1, 10, 0, 0))
    assert at.n_paths == 8
    assert "A>A" not in path_set(at)
    after = _raw(mini, settings, since=datetime(2026, 3, 1, 10, 0, 1))
    assert after.n_paths == 0


def test_ac3_unknown_account_returns_empty(mini: DuckDb, settings: Settings) -> None:
    result = trace(mini, settings, "ZZZ", hops=3, hours=24)
    assert result.n_paths == 0
    assert len(result.paths) == 0
    assert list(result.paths.columns) == PATH_COLUMNS


def test_ac3_defaults_come_from_config(mini: DuckDb, settings: Settings) -> None:
    result = trace(mini, settings, "A")
    assert result.request.hops == 3
    assert result.request.hours == 72


# ----------------------------------------------------------------------------- AC4
def test_ac4_edge_unfiltered_is_superset(mini: DuckDb, settings: Settings) -> None:
    result = _edge(mini, settings, min_amount_vnd=0, top_k=0)
    assert result.method == "cte_edge"
    assert result.n_paths == 12
    assert result.n_cycles == 3
    assert path_set(result) == set(AC2_PATHS) | {"A>B>E", "A>B>H", "A>B>C>D>G"}


def test_ac4_edge_row_shape(mini: DuckDb, settings: Settings) -> None:
    paths = _edge(mini, settings, min_amount_vnd=0, top_k=0).paths
    assert list(paths.columns) == PATH_COLUMNS
    row = paths[paths["path"] == "A>B>C>D"].iloc[0]
    assert row["step_path"] == "2026-03-01>2026-03-01>2026-03-02"
    assert int(row["amount_vnd"]) == 70_000_000
    assert pd.Timestamp(row["last_ts"]) == pd.Timestamp("2026-03-02 00:00:00")


def test_ac4_edge_min_amount(mini: DuckDb, settings: Settings) -> None:
    result = _edge(mini, settings, min_amount_vnd=20_000_000, top_k=0)
    assert result.n_paths == 9
    found = path_set(result)
    for gone in ("A>A", "A>B>C>B", "A>B>C>EXT-000001>K"):
        assert gone not in found, gone


def test_ac4_edge_top_k_2(mini: DuckDb, settings: Settings) -> None:
    result = _edge(mini, settings, min_amount_vnd=0, top_k=2)
    assert result.n_paths == 8
    assert path_set(result) == {
        "A>A",
        "A>B",
        "A>B>C",
        "A>B>E",
        "A>B>C>A",
        "A>B>C>D",
        "A>B>C>D>F",
        "A>B>C>D>G",
    }


def test_ac4_edge_min_amount_and_top_k_1(mini: DuckDb, settings: Settings) -> None:
    result = _edge(mini, settings, min_amount_vnd=20_000_000, top_k=1)
    assert sorted(result.paths["path"]) == ["A>B", "A>B>C", "A>B>C>A"]
    last = result.paths[result.paths["path"] == "A>B>C>A"].iloc[0]
    assert bool(last["is_cycle"]) is True


def test_ac4_cte_raw_ignores_min_amount_and_top_k(mini: DuckDb, settings: Settings) -> None:
    result = _raw(mini, settings, min_amount_vnd=20_000_000, top_k=1)
    assert rows_of(result.paths) == AC2_ROWS


# ----------------------------------------------------------------------------- AC7
def test_ac7_invalid_method_lists_the_methods(mini: DuckDb, settings: Settings) -> None:
    with pytest.raises(mod("aml.graph.trace").TraceError, match="cte_raw, cte_edge, pgq"):
        trace(mini, settings, "A", method="bfs", hops=2, hours=24)


@pytest.mark.parametrize(
    ("account", "kw"),
    [
        ("", {}),
        ("A>B", {}),
        ("A", {"hops": 0}),
        ("A", {"hours": 0}),
        ("A", {"hours": 721}),
        ("A", {"method": "cte_edge", "min_amount_vnd": -1}),
        ("A", {"method": "cte_edge", "top_k": -1}),
    ],
)
def test_ac7_invalid_input_raises(
    mini: DuckDb, settings: Settings, account: str, kw: dict[str, Any]
) -> None:
    with pytest.raises(mod("aml.graph.trace").TraceError):
        trace(mini, settings, account, **{"hops": 2, "hours": 24, **kw})


def test_ac7_hops_above_max_names_the_bounds(mini: DuckDb, settings: Settings) -> None:
    with pytest.raises(mod("aml.graph.trace").TraceError) as err:
        trace(mini, settings, "A", hops=7, hours=24)
    assert "1" in str(err.value)
    assert "6" in str(err.value)


def test_ac7_pgq_on_duckdb_is_oracle_only(mini: DuckDb, settings: Settings) -> None:
    with pytest.raises(mod("aml.graph.trace").TraceError, match="Oracle only"):
        trace(mini, settings, "A", method="pgq", hops=2, hours=24)


def test_ac7_max_paths_is_an_error_not_a_truncation(mini: DuckDb) -> None:
    small = load_settings(environ={"AML__TRACE__MAX_PATHS": "8"})
    with pytest.raises(mod("aml.graph.trace").TraceError, match="more than 8 paths"):
        trace(mini, small, "A", hops=4, hours=24)
    assert trace(mini, small, "A", hops=2, hours=24).n_paths == 3


def test_ac7_errors_write_no_audit(mini: DuckDb) -> None:
    trace_error = mod("aml.graph.trace").TraceError
    small = load_settings(environ={"AML__TRACE__MAX_PATHS": "8"})
    calls: list[tuple[str, dict[str, Any]]] = [
        ("A", {"method": "bfs"}),
        ("", {}),
        ("A>B", {}),
        ("A", {"hops": 0}),
        ("A", {"hops": 7}),
        ("A", {"hours": 0}),
        ("A", {"hours": 721}),
        ("A", {"method": "cte_edge", "min_amount_vnd": -1}),
        ("A", {"method": "cte_edge", "top_k": -1}),
        ("A", {"method": "pgq"}),
        ("A", {"hops": 4}),
    ]
    for account, kw in calls:
        with pytest.raises(trace_error):
            trace(mini, small, account, **{"hops": 2, "hours": 24, **kw})
    assert int(scalar(mini, "SELECT COUNT(*) FROM audit_log WHERE module = 'graph'")) == 0


# ----------------------------------------------------------------------------- AC8
def test_ac8_audit_rows(mini: DuckDb, settings: Settings) -> None:
    trace(mini, settings, "A", method="cte_raw", hops=4, hours=24, actor="analyst01")
    trace(mini, settings, "A", method="cte_edge", hops=4, hours=24)
    trace(mini, settings, "A", method="cte_raw", hops=4, hours=24, record_audit=False)

    audit = graph_audit(mini)
    assert len(audit) == 2
    assert set(audit["entity_type"]) == {"account"}
    assert set(audit["entity_id"]) == {"A"}
    assert set(audit["decision"]) == {"TRACED"}
    assert all(isinstance(r, str) and r.strip() for r in audit["reason"])

    first, second = audit.iloc[0], audit.iloc[1]
    assert first["version"] == "trace/cte_raw"
    assert first["actor"] == "analyst01"
    d = first["details"]
    assert d["method"] == "cte_raw"
    assert d["backend"] == "duckdb"
    assert d["hops"] == 4
    assert d["hours"] == 24
    assert d["since"] is None
    assert d["paths"] == 9
    assert d["accounts"] == 6
    assert d["cycles"] == 3

    assert second["version"] == "trace/cte_edge"
    assert second["actor"] == "system"
    assert second["details"]["min_amount_vnd"] == 10_000_000
    assert second["details"]["top_k"] == 5


def test_ac8_trace_is_read_only(mini: DuckDb, settings: Settings) -> None:
    trace(mini, settings, "A", method="cte_raw", hops=4, hours=24, actor="analyst01")
    trace(mini, settings, "A", method="cte_edge", hops=4, hours=24)
    trace(mini, settings, "A", method="cte_raw", hops=4, hours=24, record_audit=False)
    assert int(scalar(mini, "SELECT COUNT(*) FROM transactions")) == 14
    assert int(scalar(mini, "SELECT COUNT(*) FROM acct_edge_daily")) == 12
