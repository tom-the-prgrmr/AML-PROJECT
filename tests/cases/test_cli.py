"""AC9 for specs/case-consolidation.md: `aml cases build|show|dispose` (DuckDB, TINY)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from aml.common.db import DuckDb

from .helpers import TINY_CASE, cli, count, has, mod

UseStage = Callable[[str], Path]


def _count(path: Path, table: str, where: str = "") -> int:
    with DuckDb(path) as db:
        mod("aml.dba.schema").apply_schema(db)  # idempotent; makes sure the tables exist
        return count(db, table, where)


def test_ac9_build_prints_the_summary_line(cli_db: UseStage) -> None:
    cli_db("sources")
    result = cli("cases", "build")
    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.stdout.splitlines() if "run_id=1" in ln]
    assert len(lines) == 1
    for token in (
        "run_id=1",
        "as_of=2026-06-30",
        "items=74",
        "alerts=40",
        "suppressed=0",
        "active=74",
        "cases=52",
        "opened=52",
        "reopened=0",
        "closed=0",
        "graph_features=networkx",
    ):
        assert has(lines[0], token), token


def test_ac9_show_and_dispose(cli_db: UseStage) -> None:
    cli_db("sources")
    assert cli("cases", "build").exit_code == 0

    shown = cli("cases", "show", TINY_CASE)
    assert shown.exit_code == 0, shown.output
    first = shown.stdout.splitlines()[0]
    for token in (TINY_CASE, "OPEN", "G-CIF00000189", "alerts=5"):
        assert token in first, token
    assert "txn_summary" in shown.stdout

    disposed = cli(
        "cases",
        "dispose",
        TINY_CASE,
        "--disposition",
        "SUSPICIOUS",
        "--reason",
        "collector of a mule ring",
        "--actor",
        "analyst01",
    )
    assert disposed.exit_code == 0, disposed.output
    assert "disposition_id=1" in disposed.stdout


def test_ac9_unknown_case_exits_1(cli_db: UseStage) -> None:
    cli_db("sources")
    assert cli("cases", "build").exit_code == 0
    result = cli("cases", "show", "C-NOPE-20260101")
    assert result.exit_code == 1, result.output
    assert "unknown case_id" in result.stderr


def test_ac9_bad_disposition_exits_2(cli_db: UseStage) -> None:
    cli_db("sources")
    assert cli("cases", "build").exit_code == 0
    result = cli(
        "cases", "dispose", TINY_CASE, "--disposition", "MAYBE", "--reason", "x", "--actor", "a"
    )
    assert result.exit_code == 2, result.output


def test_ac9_bad_as_of_exits_2_without_a_run(cli_db: UseStage) -> None:
    path = cli_db("sources")
    assert cli("cases", "build").exit_code == 0
    result = cli("cases", "build", "--as-of", "2026-13-01")
    assert result.exit_code == 2, result.output
    assert _count(path, "case_runs") == 1


def test_ac9_help_lists_cases() -> None:
    result = cli("--help")
    assert result.exit_code == 0, result.output
    assert "cases" in result.stdout


def test_ac9_build_without_er_fails_cleanly(cli_db: UseStage) -> None:
    path = cli_db("load")
    result = cli("cases", "build")
    assert result.exit_code == 1, result.output
    assert "run `aml er` first" in result.stderr
    assert _count(path, "case_runs") == 0
    assert _count(path, "audit_log", "WHERE module = 'cases'") == 0


def test_ac9_build_without_sources_fails_cleanly(cli_db: UseStage) -> None:
    path = cli_db("er")
    result = cli("cases", "build")
    assert result.exit_code == 1, result.output
    assert "run `aml screen` or `aml monitor` first" in result.stderr
    assert _count(path, "case_runs") == 0
    assert _count(path, "audit_log", "WHERE module = 'cases'") == 0
