"""AC9-AC10 for specs/dq-framework.md: Oracle/DuckDB parity and the `aml dq run` command."""

from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aml.common.config import get_settings, load_settings, read_environ
from aml.common.db import DuckDb, OracleDb

from .helpers import ALL_RULES, by_rule, mod


@pytest.mark.oracle
def test_ac9_oracle_and_duckdb_agree_on_tiny(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    load = mod("aml.datagen.load")
    runner = mod("aml.dq.runner")
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle")})
    with OracleDb(osettings) as odb:
        load.load_parquet(odb, tiny_parquet)
        orun = runner.run_dq(odb, osettings, as_of=date(2026, 6, 30))
        tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
        views = set(odb.query_df("SELECT view_name FROM user_views").iloc[:, 0])
        trend_n = int(
            odb.query_df(f"SELECT COUNT(*) FROM dq_trend WHERE run_id = {orun.run_id}").iloc[0, 0]
        )
    assert {"DQ_RULES", "DQ_RESULTS"} <= tables
    assert "DQ_TREND" in views
    assert trend_n == 10

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb"})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        load.load_parquet(ddb, tiny_parquet)
        drun = runner.run_dq(ddb, dsettings, as_of=date(2026, 6, 30))

    o, d = by_rule(orun), by_rule(drun)
    assert set(o) == set(d) == set(ALL_RULES)
    for rule_id in ALL_RULES:
        a, b = o[rule_id], d[rule_id]
        assert (a.total_rows, a.failed_rows, a.fail_rate, a.status) == (
            b.total_rows,
            b.failed_rows,
            b.fail_rate,
            b.status,
        ), rule_id
        assert a.failed_ids == b.failed_ids, rule_id


def _cli_app() -> Any:
    return importlib.import_module("aml.cli").app


def _result_count(db_path: Path) -> int:
    with DuckDb(db_path) as db:
        return int(db.query_df("SELECT COUNT(*) FROM dq_results").iloc[0, 0])


def test_ac10_cli_dq_run_prints_results_and_rejects_bad_date(
    tiny_env: Any,
    tiny_parquet: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = tiny_env()
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    db_path = tmp_path / "tiny.duckdb"
    with DuckDb(db_path) as db:
        mod("aml.datagen.load").load_parquet(db, tiny_parquet)

    result = CliRunner().invoke(_cli_app(), ["dq", "run"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    rule_lines = [
        ln
        for ln in lines
        if "precision=" not in ln
        and ("PASS" in ln or "FAIL" in ln)
        and any(r in ln for r in ALL_RULES)
    ]
    assert len(rule_lines) == 10
    for rule_id in ALL_RULES:
        assert sum(rule_id in ln for ln in rule_lines) == 1, rule_id
    summary = [ln for ln in lines if "run_id=1" in ln]
    assert len(summary) == 1
    assert "4 PASS" in summary[0]
    assert "6 FAIL" in summary[0]
    assert sum("precision=1.00 recall=1.00" in ln for ln in lines) == 5
    assert _result_count(db_path) == 10

    bad = CliRunner().invoke(_cli_app(), ["dq", "run", "--as-of", "2026-13-01"])
    assert bad.exit_code == 2, bad.output
    assert _result_count(db_path) == 10
