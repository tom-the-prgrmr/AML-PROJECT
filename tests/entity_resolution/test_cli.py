"""AC9 for specs/entity-resolution.md: `aml er`, `--eval-out`, `--explain`, `--as-of`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aml.common.config import get_settings
from aml.common.db import DuckDb

from .helpers import load_tiny_duck, mod, scalar


def _cli(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, list(args))


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def _count(path: Path, sql: str) -> int:
    with DuckDb(path) as db:
        return int(scalar(db, sql))


def test_ac9_er_run_prints_summary_eval_and_csv(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb").close()
    out = tmp_path / "er_eval.csv"

    result = _cli("er", "--eval-out", str(out))
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    summary = [ln for ln in lines if "run_id=1" in ln]
    assert len(summary) == 1
    for token in (
        "customers=300",
        "blocked_pairs=53",
        "MATCH=32",
        "REVIEW=0",
        "clusters=273",
        "merged_clusters=22",
    ):
        assert token in summary[0], token

    pairwise = [ln for ln in lines if ln.startswith("pairwise")]
    cluster = [ln for ln in lines if ln.startswith("cluster")]
    assert len(pairwise) == 1 and len(cluster) == 1
    assert lines.index(pairwise[0]) < lines.index(cluster[0])
    for token in ("predicted=32", "truth=32", "precision=1.00 recall=1.00"):
        assert token in pairwise[0], token
    for token in ("predicted=22", "truth=22", "precision=1.00 recall=1.00"):
        assert token in cluster[0], token

    csv_lines = out.read_text(encoding="utf-8").splitlines()
    assert csv_lines[0] == "level,predicted,truth,tp,fp,fn,precision,recall"
    assert len([ln for ln in csv_lines[1:] if ln.strip()]) == 2


def test_ac9_explain_reads_current_run_without_rerunning(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    path = tmp_path / "tiny.duckdb"
    load_tiny_duck(tiny_parquet, path).close()
    assert _cli("er").exit_code == 0

    result = _cli("er", "--explain", "G-CIF00000047")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    head = [ln for ln in lines if "G-CIF00000047" in ln]
    assert len(head) == 1
    for token in ("cluster_size=3", "min_match_weight=37.00"):
        assert token in head[0], token
    pair_lines = [ln for ln in lines if "weight=" in ln and "cluster_size=" not in ln]
    assert len(pair_lines) == 3
    target = [ln for ln in pair_lines if "CIF00000047" in ln and "CIF00000268" in ln]
    assert len(target) == 1
    for token in ("weight=48.46", "name=+8.76", "email=+10.60"):
        assert token in target[0], token
    assert _count(path, "SELECT COUNT(*) FROM er_runs") == 1


def test_ac9_explain_unknown_id_exits_1(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb").close()
    assert _cli("er").exit_code == 0
    result = _cli("er", "--explain", "G-NOPE")
    assert result.exit_code == 1, result.output
    assert "unknown golden_customer_id" in result.stderr


def test_ac9_bad_as_of_exits_2_without_a_run(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    path = tmp_path / "tiny.duckdb"
    load_tiny_duck(tiny_parquet, path).close()
    assert _cli("er").exit_code == 0
    result = _cli("er", "--as-of", "2026-13-01")
    assert result.exit_code == 2, result.output
    assert _count(path, "SELECT COUNT(*) FROM er_runs") == 1


def test_ac9_without_load_fails_cleanly(
    tiny_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    path = tmp_path / "tiny.duckdb"
    with DuckDb(path) as db:
        mod("aml.dba.schema").apply_schema(db)
    result = _cli("er")
    assert result.exit_code == 1, result.output
    assert "run `aml load` first" in result.stderr
    assert _count(path, "SELECT COUNT(*) FROM er_runs") == 0
    assert _count(path, "SELECT COUNT(*) FROM audit_log WHERE module = 'entity_resolution'") == 0
