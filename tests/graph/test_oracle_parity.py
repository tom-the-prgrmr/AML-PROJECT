"""AC9 for specs/fund-flow-trace.md: Oracle (cte_raw, pgq, cte_edge) agrees with DuckDB."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import Database, OracleDb

from .helpers import (
    AC2_ROWS,
    HUB,
    MULE,
    PAYROLL,
    RND,
    duck_settings,
    load_mini,
    load_tiny_duck,
    mod,
    rows_of,
    scalar,
    trace,
)

# (account, hops, hours, expected rows of the exact methods)
EXACT_CASES = [
    (RND, 4, 168, 4),
    (RND, 4, 72, 2),
    (HUB, 6, 168, 41),
    (MULE, 4, 168, 104),
    (PAYROLL, 2, 24, 120),
]
GRAPH_COUNT_SQL = (
    "SELECT COUNT(*) FROM GRAPH_TABLE(aml_fund_flow MATCH (a IS account) -[e IS transfer]-> "
    "(b IS account) COLUMNS (e.txn_id AS txn_id))"
)


def _norm(paths: pd.DataFrame) -> pd.DataFrame:
    """Same frame with timestamps floored to the second (Oracle and DuckDB differ in unit)."""
    out = paths.copy()
    out.columns = [c.lower() for c in out.columns]
    for col in ("first_ts", "last_ts"):
        out[col] = pd.to_datetime(out[col]).dt.floor("s").astype("datetime64[ns]")
    return out.reset_index(drop=True)


def _same(a: Any, b: Any) -> None:
    pd.testing.assert_frame_equal(_norm(a.paths), _norm(b.paths))


def _oracle_settings(tiny_env: Any) -> Settings:
    return load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle")})


@pytest.mark.oracle
def test_ac9_oracle_objects_and_idempotent_schema(tiny_env: Any, tiny_parquet: Path) -> None:
    osettings = _oracle_settings(tiny_env)
    with OracleDb(osettings) as odb:
        mod("aml.datagen.load").load_parquet(odb, tiny_parquet)
        graphs = odb.query_df("SELECT graph_name FROM user_property_graphs").iloc[:, 0]
        assert "AML_FUND_FLOW" in set(graphs)
        mviews = odb.query_df("SELECT mview_name FROM user_mviews").iloc[:, 0]
        assert "ACCT_NODE" in set(mviews)
        assert int(scalar(odb, "SELECT COUNT(*) FROM acct_node")) == 1149
        assert int(scalar(odb, GRAPH_COUNT_SQL)) == 3651
        mod("aml.dba.schema").apply_schema(odb)  # second call must not raise


@pytest.mark.oracle
def test_ac9_cte_raw_pgq_and_duckdb_agree_on_tiny(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    osettings = _oracle_settings(tiny_env)
    dsettings = duck_settings()
    duck = load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb")
    try:
        with OracleDb(osettings) as odb:
            mod("aml.datagen.load").load_parquet(odb, tiny_parquet)
            for account, hops, hours, rows in EXACT_CASES:
                kw: dict[str, Any] = {"hops": hops, "hours": hours, "record_audit": False}
                o_raw = trace(odb, osettings, account, method="cte_raw", **kw)
                o_pgq = trace(odb, osettings, account, method="pgq", **kw)
                d_raw = trace(duck, dsettings, account, method="cte_raw", **kw)
                assert (o_raw.backend, o_pgq.backend, d_raw.backend) == (
                    "oracle",
                    "oracle",
                    "duckdb",
                )
                assert o_raw.n_paths == o_pgq.n_paths == d_raw.n_paths == rows
                _same(o_raw, d_raw)
                _same(o_pgq, d_raw)
                if account == HUB:
                    assert o_raw.n_cycles == o_pgq.n_cycles == d_raw.n_cycles == 4
    finally:
        duck.close()


@pytest.mark.oracle
def test_ac9_cte_edge_oracle_equals_duckdb(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    osettings = _oracle_settings(tiny_env)
    dsettings = duck_settings()
    duck = load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb")
    try:
        with OracleDb(osettings) as odb:
            mod("aml.datagen.load").load_parquet(odb, tiny_parquet)
            for account, hops, hours, _ in EXACT_CASES:
                base: dict[str, Any] = {"hops": hops, "hours": hours, "record_audit": False}
                for extra in ({"min_amount_vnd": 0, "top_k": 0}, {}):
                    o_edge = trace(odb, osettings, account, method="cte_edge", **base, **extra)
                    d_edge = trace(duck, dsettings, account, method="cte_edge", **base, **extra)
                    _same(o_edge, d_edge)
    finally:
        duck.close()


@pytest.mark.oracle
def test_ac9_pgq_query_grows_with_hops_and_ends_in_cycle(tiny_env: Any, tiny_parquet: Path) -> None:
    osettings = _oracle_settings(tiny_env)
    with OracleDb(osettings) as odb:
        mod("aml.datagen.load").load_parquet(odb, tiny_parquet)
        four = trace(odb, osettings, RND, method="pgq", hops=4, hours=168, record_audit=False)
        two = trace(odb, osettings, RND, method="pgq", hops=2, hours=168, record_audit=False)
        assert bool(four.paths.iloc[-1]["is_cycle"]) is True
        assert four.query_lines > two.query_lines


def _load_mini_oracle(odb: Database) -> int:
    schema = mod("aml.dba.schema")
    schema.apply_schema(odb)
    odb.execute("DELETE FROM transactions")
    load_mini(odb)
    return int(mod("aml.graph.schema").refresh_account_nodes(odb))


@pytest.mark.oracle
def test_ac9_mini_on_oracle(tiny_env: Any, tiny_parquet: Path) -> None:
    osettings = _oracle_settings(tiny_env)
    with OracleDb(osettings) as odb:
        try:
            assert _load_mini_oracle(odb) == 10
            for method in ("cte_raw", "pgq"):
                result = trace(
                    odb, osettings, "A", method=method, hops=4, hours=24, record_audit=False
                )
                assert rows_of(result.paths) == AC2_ROWS, method
        finally:
            # the shared owner schema is expected to hold TINY for the other Oracle tests
            mod("aml.datagen.load").load_parquet(odb, tiny_parquet)
