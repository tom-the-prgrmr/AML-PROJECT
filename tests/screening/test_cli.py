"""AC9 for specs/screening-tiers-eval.md: the `aml screen` command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aml.common.config import get_settings
from aml.common.db import DuckDb

from .helpers import mod
from .helpers_3b import EVAL_METHODS, load_tiny_duck


def _screen(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, ["screen", *args])


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def _count(db_path: Path, sql: str) -> int:
    with DuckDb(db_path) as db:
        return int(db.query_df(sql).iloc[0, 0])


def test_ac9_screen_prints_summary_and_evaluation_and_writes_csv(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    db_path = tmp_path / "tiny.duckdb"
    load_tiny_duck(tiny_parquet, db_path).close()
    out = tmp_path / "eval.csv"

    result = _screen("--eval-out", str(out))
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    summary = [ln for ln in lines if "run_id=1" in ln]
    assert len(summary) == 1
    for token in ("mode=FULL", "customers=300", "entries=200", "ALERT=5", "REVIEW=0"):
        assert token in summary[0], token
    ev = [ln for ln in lines if ln.split(" ")[0] in EVAL_METHODS]
    assert [ln.split()[0] for ln in ev] == list(EVAL_METHODS)
    assert "flagged=55" in ev[1] and "precision=0.09" in ev[1]
    assert "precision=1.00 recall=1.00" in ev[3] and "fp_reduction=100.00%" in ev[3]

    csv_lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert csv_lines[0] == "method,flagged,tp,fp,fn,precision,recall,fp_reduction_pct"
    assert len(csv_lines) == 5

    bad = _screen("--as-of", "2026-13-01")
    assert bad.exit_code == 2, bad.output
    assert _count(db_path, "SELECT COUNT(*) FROM screening_runs") == 1


def test_ac9_screen_without_loaded_data_fails_cleanly(
    tiny_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    db_path = tmp_path / "tiny.duckdb"
    with DuckDb(db_path) as db:
        mod("aml.dba.schema").apply_schema(db)
    result = _screen()
    assert result.exit_code == 1, result.output
    assert "run `aml load` first" in result.stderr
    assert _count(db_path, "SELECT COUNT(*) FROM screening_runs") == 0
    assert _count(db_path, "SELECT COUNT(*) FROM audit_log WHERE module = 'screening'") == 0
