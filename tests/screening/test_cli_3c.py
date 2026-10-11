"""AC10 for specs/screening-oracle-incremental.md: screen --incremental and screen-compare."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aml.common.config import get_settings

from .helpers import mod
from .helpers_3b import load_tiny_duck


def _cli(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, list(args))


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def test_ac10_incremental_and_compare_commands(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb").close()

    first = _cli("screen")
    assert first.exit_code == 0, first.output
    second = _cli("screen", "--incremental")
    assert second.exit_code == 0, second.output
    summary = [ln for ln in second.stdout.splitlines() if "run_id=2" in ln]
    assert len(summary) == 1
    for token in ("mode=INCREMENTAL", "customers=0", "entries=0", "ALERT=0"):
        assert token in summary[0], token

    third = _cli("screen-compare")
    assert third.exit_code == 0, third.output
    lines = [ln for ln in third.stdout.splitlines() if "backend=duckdb" in ln]
    assert len(lines) == 1
    for token in (
        "function=jaro_winkler_similarity",
        "threshold=90",
        "sql_pairs=32",
        "python_pairs=5",
        "both=5",
        "sql_only=27",
        "python_only=0",
    ):
        assert token in lines[0], token


def test_ac10_compare_without_screening_fails_cleanly(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb").close()
    result = _cli("screen-compare")
    assert result.exit_code == 1, result.output
    assert "run `aml screen` first" in result.stderr
