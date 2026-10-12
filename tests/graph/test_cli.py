"""AC10 for specs/fund-flow-trace.md: `aml trace` on TINY (DuckDB)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aml.common.config import get_settings

from .helpers import MULE, RND, RND_CYCLE, load_tiny_duck, mod


def _cli(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, list(args))


@pytest.fixture
def cli_tiny(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for k, v in tiny_env().items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb").close()


def _summaries(stdout: str, method: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if f"method={method}" in ln.split()]


def test_ac10_trace_prints_summary_and_cycle_path(cli_tiny: None) -> None:
    result = _cli("trace", "--account", RND, "--hops", "4", "--hours", "168")
    assert result.exit_code == 0, result.output
    summary = _summaries(result.stdout, "cte_raw")
    assert len(summary) == 1
    tokens = summary[0].split()
    for token in (
        "method=cte_raw",
        "backend=duckdb",
        f"account={RND}",
        "hops=4",
        "hours=168",
        "paths=4",
        "accounts=3",
        "cycles=1",
    ):
        assert token in tokens, token
    cycle_lines = [ln for ln in result.stdout.splitlines() if RND_CYCLE in ln]
    assert len(cycle_lines) == 1
    assert "CYCLE" in cycle_lines[0]


def test_ac10_trace_cte_edge_defaults_and_limit(cli_tiny: None) -> None:
    result = _cli(
        "trace", "--account", MULE, "--hops", "4", "--hours", "168", "--method", "cte_edge"
    )
    assert result.exit_code == 0, result.output
    assert "paths=25" in _summaries(result.stdout, "cte_edge")[0].split()

    result = _cli(
        "trace",
        "--account",
        MULE,
        "--hops",
        "4",
        "--hours",
        "168",
        "--method",
        "cte_edge",
        "--min-amount",
        "0",
        "--top-k",
        "0",
        "--limit",
        "3",
    )
    assert result.exit_code == 0, result.output
    assert "paths=104" in _summaries(result.stdout, "cte_edge")[0].split()
    path_lines = [ln for ln in result.stdout.splitlines() if f"{MULE}>" in ln]
    assert len(path_lines) == 3


def test_ac10_trace_method_all_skips_pgq_on_duckdb(cli_tiny: None) -> None:
    result = _cli("trace", "--account", RND, "--hops", "4", "--hours", "168", "--method", "all")
    assert result.exit_code == 0, result.output
    assert len(_summaries(result.stdout, "cte_raw")) == 1
    assert len(_summaries(result.stdout, "cte_edge")) == 1
    skipped = [ln for ln in result.stdout.splitlines() if "method=pgq skipped: Oracle only" in ln]
    assert len(skipped) == 1


def test_ac10_trace_pgq_on_duckdb_exits_2(cli_tiny: None) -> None:
    result = _cli("trace", "--account", RND, "--method", "pgq")
    assert result.exit_code == 2
    assert "Oracle only" in result.stderr


def test_ac10_trace_invalid_hops_exits_2(cli_tiny: None) -> None:
    result = _cli("trace", "--account", RND, "--hops", "7")
    assert result.exit_code == 2
    assert "hops" in result.stderr


@pytest.mark.parametrize("command", ["bench"])
def test_ac10_phase_6_stubs_are_untouched(command: str) -> None:
    result = _cli(command)
    assert result.exit_code == 1
    assert "Phase 6" in result.stderr
