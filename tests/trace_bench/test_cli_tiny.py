"""AC5 for specs/trace-benchmark.md: `aml bench` and `pick_accounts` on TINY (DuckDB, offline)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import load_settings
from aml.common.db import DuckDb

from .helpers import OFFLINE_URI, cli, mod, set_env

ACCOUNT = "A7341585768"


@pytest.fixture
def bench_env(
    er_template: Path, tiny_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """TINY + ER in the active DuckDB, Neo4j offline; returns the results directory."""
    shutil.copy(er_template, tmp_path / "tiny.duckdb")
    out = tmp_path / "bench"
    set_env(
        monkeypatch,
        {
            **tiny_env(),
            "AML__NEO4J__URI": OFFLINE_URI,
            "AML__BENCH__HOURS": "[168, 720]",
            "AML__BENCH__RUNS": "5",
            "AML__BENCH__RESULTS_DIR": str(out),
        },
    )
    return out


def _names(directory: Path) -> set[str]:
    return {p.name for p in directory.iterdir()}


def test_ac5_cli_bench_output(bench_env: Path) -> None:
    result = cli("bench")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    summary = (
        f"bench profile=small backend=duckdb accounts={ACCOUNT} cells=24 ok=12 skipped=12 error=0"
    )
    assert len([ln for ln in lines if summary in ln]) == 1, lines
    assert len([ln for ln in lines if "method=pgq skipped: not available on duckdb" in ln]) == 1
    assert (
        len([ln for ln in lines if ln.startswith("method=neo4j skipped: neo4j not available")]) == 1
    )
    assert len([ln for ln in lines if ln.startswith("wrote")]) == 3
    assert _names(bench_env) == {"bench_small_duckdb.json", "bench_report.md", "bench_chart.svg"}


def test_ac5_result_file_content(bench_env: Path) -> None:
    assert cli("bench").exit_code == 0
    meta = json.loads((bench_env / "bench_small_duckdb.json").read_text(encoding="utf-8"))["meta"]
    assert meta["profile"] == "small"
    assert meta["dataset"]["transactions"] == 5100
    assert meta["dataset"]["transfers"] == 3651
    assert meta["params"]["accounts"] == [ACCOUNT]

    cells = mod("aml.graph.bench.report").read_results(bench_env)[0].cells
    assert len(cells) == 24

    def pick(method: str, hours: int, attr: str) -> list[Any]:
        chosen = [c for c in cells if c.method == method and c.hours == hours]
        assert [c.hops for c in chosen] == [2, 4, 6]
        return [getattr(c, attr) for c in chosen]

    assert pick("cte_raw", 168, "n_paths") == [34, 34, 34]
    assert pick("cte_raw", 720, "n_paths") == [92, 125, 125]
    assert pick("cte_raw", 720, "n_accounts") == [12, 19, 19]
    assert pick("cte_raw", 720, "n_cycles") == [15, 31, 31]
    assert pick("cte_edge", 168, "n_paths") == [1, 1, 1]
    assert pick("cte_edge", 720, "n_paths") == [3, 3, 3]


def test_ac5_report_table_has_24_rows(bench_env: Path) -> None:
    assert cli("bench").exit_code == 0
    text = (bench_env / "bench_report.md").read_text(encoding="utf-8")
    assert len([ln for ln in text.splitlines() if ln.startswith("| small | duckdb |")]) == 24


def test_ac5_profile_option_names_the_file(bench_env: Path) -> None:
    assert cli("bench").exit_code == 0
    result = cli("bench", "--profile", "dense-test")
    assert result.exit_code == 0, result.output
    assert "bench_dense-test_duckdb.json" in _names(bench_env)
    assert len(_names(bench_env)) == 4


def test_ac5_pick_accounts_top_three(tiny_er: DuckDb) -> None:
    runner = mod("aml.graph.bench.runner")
    settings = load_settings(environ={"DB_BACKEND": "duckdb", "AML__BENCH__TOP_ACCOUNTS": "3"})
    assert runner.pick_accounts(tiny_er, settings) == [
        ACCOUNT,
        "A1401926848",
        "A2459177476",
    ]


def test_ac5_pick_accounts_tie_goes_to_smaller_id(tiny_er: DuckDb) -> None:
    runner = mod("aml.graph.bench.runner")
    settings = load_settings(environ={"DB_BACKEND": "duckdb", "AML__BENCH__HOURS": "[168]"})
    assert runner.pick_accounts(tiny_er, settings) == ["A5040436031"]


def test_ac5_help_lists_bench() -> None:
    assert "bench" in cli("--help").stdout
    result = cli("bench", "--help")
    assert result.exit_code == 0, result.output
    assert "--report-only" in result.stdout
