"""AC10 for specs/oracle-retention.md: the `aml retention` command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aml.common.config import get_settings, read_environ
from aml.common.db import OracleDb
from tests.datagen.conftest import EnvFactory

from .helpers import count_txn, mod


def _run(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, ["retention", *args])


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def _archive_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


def test_ac10_duckdb_execute_exits_2_oracle_only(
    tiny_env: EnvFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arch = tmp_path / "arch"
    _set_env(monkeypatch, tiny_env(AML__RETENTION__ARCHIVE_DIR=str(arch)))
    result = _run("--execute")
    assert result.exit_code == 2, result.output
    assert "Oracle only" in result.output
    assert _archive_files(arch) == []


def test_ac10_below_legal_minimum_exits_2(
    tiny_env: EnvFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tiny_env(
        AML__RETENTION__TRANSACTIONS_MONTHS="59", AML__RETENTION__ARCHIVE_DIR=str(tmp_path / "a")
    )
    _set_env(monkeypatch, env)
    result = _run()
    assert result.exit_code == 2, result.output
    assert "legal minimum of 60 months" in result.output


def test_ac10_bad_as_of_exits_2(
    tiny_env: EnvFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env(AML__RETENTION__ARCHIVE_DIR=str(tmp_path / "a")))
    result = _run("--as-of", "2026-13-01")
    assert result.exit_code == 2, result.output
    assert "No such command" not in result.output  # the command exists, the date is invalid


@pytest.mark.oracle
def test_ac10_oracle_dry_run_prints_plan_and_keeps_data(
    tiny_env: EnvFactory,
    rt_db: OracleDb,
    archive_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {
        **read_environ(),
        **tiny_env(DB_BACKEND="oracle", AML__RETENTION__ARCHIVE_DIR=str(archive_dir)),
    }
    _set_env(monkeypatch, env)
    result = _run("--as-of", "2026-06-30")
    assert result.exit_code == 0, result.output
    for needle in ("DRY RUN", "cutoff=2021-06-01", "2019-03", "2019-04"):
        assert needle in result.output, needle
    assert count_txn(rt_db, "RT1") == 1
    assert _archive_files(archive_dir) == []
