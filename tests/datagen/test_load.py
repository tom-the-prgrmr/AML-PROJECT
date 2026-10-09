"""Acceptance tests for specs/datagen-watchlist-output.md (AC9-AC11: loaders, `aml load`)."""

from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from typer.testing import CliRunner

from aml.common.config import get_settings, load_settings, read_environ
from aml.common.db import DuckDb, OracleDb

from .conftest import TABLES, EnvFactory


def _cli_app() -> Any:
    return importlib.import_module("aml.cli").app


def _manifest(src: Path) -> dict[str, Any]:
    return json.loads((src / "manifest.json").read_text(encoding="utf-8"))


def _init_audit(db_path: Path) -> None:
    with DuckDb(db_path) as db:
        db.run_named_script("ddl/000_audit_log.sql")


def _counts(db_path: Path) -> dict[str, int]:
    """Row counts of the data tables that exist in the DuckDB file."""
    with DuckDb(db_path) as db:
        existing = set(
            db.query_df("SELECT table_name FROM information_schema.tables")["table_name"]
        )
        return {
            t: int(db.query_df(f"SELECT COUNT(*) AS n FROM {t}")["n"].iloc[0])
            for t in TABLES
            if t in existing
        }


def _find_counts(node: Any, tables: dict[str, int]) -> bool:
    """True if some dict inside the JSON ``details`` maps every table to its row count."""
    if isinstance(node, dict):
        if all(node.get(t) == n for t, n in tables.items()):
            return True
        return any(_find_counts(v, tables) for v in node.values())
    return False


def test_ac9_load_duckdb_is_idempotent_unicode_safe_and_audited(
    tiny_env: EnvFactory,
    tiny_parquet: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = tiny_env()
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    db_path = tmp_path / "tiny.duckdb"
    _init_audit(db_path)
    manifest = _manifest(tiny_parquet)
    expected = manifest["tables"]
    total = sum(expected.values())

    parquet_customers = pd.read_parquet(tiny_parquet / "customers.parquet")
    accented = parquet_customers[parquet_customers["full_name"].str.contains("Nguyễn")]
    assert len(accented) > 0

    for run in (1, 2):
        result = CliRunner().invoke(
            _cli_app(), ["load", "--backend", "duckdb", "--src", str(tiny_parquet)]
        )
        assert result.exit_code == 0, result.output
        assert _counts(db_path) == {t: expected[t] for t in TABLES}, f"run {run}"

        with DuckDb(db_path) as db:
            names = db.query_df("SELECT cif, full_name FROM customers ORDER BY cif")
            audit = db.query_df(
                "SELECT * FROM audit_log WHERE module = 'datagen' ORDER BY audit_id"
            )
        want = parquet_customers[["cif", "full_name"]].sort_values("cif").reset_index(drop=True)
        assert names.reset_index(drop=True).equals(want)

        assert len(audit) == run
        last = audit.iloc[-1]
        assert last["entity_type"] == "dataset"
        assert last["decision"] == "LOADED"
        assert last["entity_id"] == f"{manifest['profile']}-seed{manifest['seed']}"
        assert "duckdb" in last["reason"]
        assert str(total) in last["reason"]
        assert _find_counts(json.loads(last["details"]), expected)


def test_ac10_load_without_manifest_or_with_missing_file_fails_cleanly(
    tiny_env: EnvFactory,
    tiny_parquet: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k, v in tiny_env().items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    db_path = tmp_path / "tiny.duckdb"
    _init_audit(db_path)
    runner = CliRunner()

    empty = tmp_path / "empty_src"
    empty.mkdir()
    result = runner.invoke(_cli_app(), ["load", "--src", str(empty)])
    assert result.exit_code == 1
    assert "run `aml data` first" in result.output
    assert "manifest.json" in result.output
    assert _counts(db_path) == {}

    broken = tmp_path / "broken_src"
    shutil.copytree(tiny_parquet, broken)
    (broken / "transactions.parquet").unlink()
    result = runner.invoke(_cli_app(), ["load", "--src", str(broken)])
    assert result.exit_code == 1
    assert "run `aml data` first" in result.output
    assert "transactions.parquet" in result.output
    assert _counts(db_path) == {}

    # an already loaded database stays untouched by a failing load
    ok = runner.invoke(_cli_app(), ["load", "--backend", "duckdb", "--src", str(tiny_parquet)])
    assert ok.exit_code == 0, ok.output
    before = _counts(db_path)
    assert before
    result = runner.invoke(_cli_app(), ["load", "--src", str(broken)])
    assert result.exit_code == 1
    assert _counts(db_path) == before


@pytest.mark.oracle
def test_ac11_load_oracle_twice_counts_and_unicode(
    tiny_env: EnvFactory, tiny_parquet: Path
) -> None:
    load_mod = importlib.import_module("aml.datagen.load")
    settings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle")})
    manifest = _manifest(tiny_parquet)
    parquet_customers = pd.read_parquet(tiny_parquet / "customers.parquet")
    accented = parquet_customers[parquet_customers["full_name"].str.contains("Nguyễn")]
    assert len(accented) > 0
    cif = accented["cif"].iloc[0]
    want_name = accented["full_name"].iloc[0]

    with OracleDb(settings) as db:
        for _ in range(2):
            load_mod.load_parquet(db, tiny_parquet)
            for t, n in manifest["tables"].items():
                got = db.query_df(f"SELECT COUNT(*) AS n FROM {t}")["n"].iloc[0]
                assert int(got) == n, t
            row = db.query_df("SELECT full_name FROM customers WHERE cif = :1", [cif])
            assert row["full_name"].iloc[0] == want_name
