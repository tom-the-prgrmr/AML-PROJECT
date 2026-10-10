"""Acceptance tests AC9-AC10 for specs/oracle-schema-core.md (partition pruning evidence)."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aml.common.config import Settings, get_settings, load_settings, read_environ
from aml.common.db import DuckDb, OracleDb
from tests.datagen.conftest import EnvFactory

from .conftest import audit_rows


def _plans() -> Any:
    return importlib.import_module("aml.dba.plans")


def _cli_app() -> Any:
    return importlib.import_module("aml.cli").app


def _oracle_settings(tiny_env: EnvFactory) -> Settings:
    return load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle")})


def _start_stop(plan: str, operation: str) -> tuple[int, int]:
    """Pstart / Pstop (last two cells) of the plan line holding ``operation``."""
    line = next(ln for ln in plan.splitlines() if operation in ln)
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return int(cells[-2]), int(cells[-1])


@pytest.mark.oracle
def test_ac9_pruning_queries_show_expected_partition_operations(
    tiny_env: EnvFactory, tiny_parquet: Path
) -> None:
    load_mod = importlib.import_module("aml.datagen.load")
    plans = _plans()
    settings = _oracle_settings(tiny_env)
    queries = {q.name: q for q in plans.pruning_queries(settings)}
    assert set(queries) == {"single", "iterator", "all"}
    assert queries["single"].expected_op == "PARTITION RANGE SINGLE"
    assert queries["iterator"].expected_op == "PARTITION RANGE ITERATOR"
    assert queries["all"].expected_op == "PARTITION RANGE ALL"

    with OracleDb(settings) as db:
        load_mod.load_parquet(db, tiny_parquet)
        text = {n: plans.explain_plan(db, q.sql) for n, q in queries.items()}

    start, stop = _start_stop(text["single"], "PARTITION RANGE SINGLE")
    assert start == stop
    start, stop = _start_stop(text["iterator"], "PARTITION RANGE ITERATOR")
    assert stop - start == 1
    assert "PARTITION RANGE ALL" in text["all"]


def test_ac9_explain_plan_on_duckdb_is_oracle_only(duck: DuckDb) -> None:
    with pytest.raises(NotImplementedError, match="Oracle only"):
        _plans().explain_plan(duck, "SELECT 1")


def test_ac10_explain_pruning_on_duckdb_exits_2_without_file(
    tiny_env: EnvFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for k, v in tiny_env(DB_BACKEND="duckdb").items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    out = tmp_path / "p.txt"
    result = CliRunner().invoke(_cli_app(), ["explain-pruning", "--out", str(out)])
    assert result.exit_code == 2, result.output
    assert "Oracle only" in result.output
    assert not out.exists()


@pytest.mark.oracle
def test_ac10_explain_pruning_on_oracle_writes_evidence_and_audits(
    tiny_env: EnvFactory,
    tiny_parquet: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_mod = importlib.import_module("aml.datagen.load")
    env = {**read_environ(), **tiny_env(DB_BACKEND="oracle")}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    settings = load_settings(environ=env)
    with OracleDb(settings) as db:
        load_mod.load_parquet(db, tiny_parquet)
        before = len(audit_rows(db, "module = 'dba' AND decision = 'EVIDENCE_CAPTURED'"))

    out = tmp_path / "p.txt"
    result = CliRunner().invoke(_cli_app(), ["explain-pruning", "--out", str(out)])
    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    for q in _plans().pruning_queries(settings):
        assert q.name in text
        assert q.sql in text
    assert len(re.findall(r"Plan hash value", text)) == 3

    with OracleDb(settings) as db:
        rows = audit_rows(db, "module = 'dba' AND decision = 'EVIDENCE_CAPTURED'")
    assert len(rows) == before + 1
    assert rows.iloc[-1]["details"]["path"] == str(out)
