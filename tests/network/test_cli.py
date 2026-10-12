"""AC9 for specs/network-detections.md: `aml network` (DuckDB, TINY).

Output conventions chosen by the tests (the spec leaves the format open), as `aml monitor`:
  rule line      ``NET_CYCLE              alerts=2 evidence=8``
  summary line   ``run_id=2 as_of=2026-06-30 alerts=4 evidence=67 accounts=532 active_accounts=298
                 cycle_search_steps=12``
  evaluation     ``NET_CYCLE              target_hits=2 other_suspicious=0 benign=0
                 precision=1.00 recall=1.00 precision_suspicious=1.00``
  coverage       ``mule_ring        scenarios=1 rule=1 network=1 any=1 new=0 accounts=36
                 accounts_rule=14 accounts_network=29 accounts_any=36 accounts_new=22 rules=...``
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aml.common.config import get_settings
from aml.common.db import DuckDb

from .helpers import (
    COVERAGE_EXPECTED,
    EVAL_COLUMNS,
    RULE_IDS,
    TYPOLOGIES,
    duck_settings,
    has,
    lines_for,
    load_tiny_duck,
    mod,
    run_monitoring,
    scalar,
)


def _cli(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, list(args))


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def _count(path: Path, sql: str) -> int:
    with DuckDb(path) as db:
        return int(scalar(db, sql))


@pytest.fixture
def prepared(
    er_template: Path, tiny_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """TINY after `aml er` and `aml monitor` (run 1), configured as the active database."""
    path = tmp_path / "tiny.duckdb"
    shutil.copy(er_template, path)
    with DuckDb(path) as db:
        assert run_monitoring(db, duck_settings()).run_id == 1
    _set_env(monkeypatch, tiny_env())
    return path


def test_ac9_cli_network_prints_rules_summary_eval_coverage_and_csv(
    prepared: Path, tmp_path: Path
) -> None:
    out = tmp_path / "network_eval.csv"
    result = _cli("network", "--eval-out", str(out))
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()

    rule_lines = {r: lines_for(lines, r, "evidence=") for r in RULE_IDS}
    assert all(len(v) == 1 for v in rule_lines.values()), rule_lines
    for rule_id, alerts, evidence in (
        ("NET_SHARED_ATTRIBUTE", 1, 28),
        ("NET_CYCLE", 2, 8),
        ("NET_HUB", 1, 31),
    ):
        assert has(rule_lines[rule_id][0], f"alerts={alerts}"), rule_id
        assert has(rule_lines[rule_id][0], f"evidence={evidence}"), rule_id

    summary = [ln for ln in lines if "run_id=2" in ln]
    tokens = (
        "run_id=2",
        "as_of=2026-06-30",
        "alerts=4",
        "evidence=67",
        "accounts=532",
        "active_accounts=298",
        "cycle_search_steps=12",
    )
    assert any(all(has(ln, t) for t in tokens) for ln in summary), summary

    eval_lines = {r: lines_for(lines, r, "target_hits=") for r in RULE_IDS}
    assert all(len(v) == 1 for v in eval_lines.values()), eval_lines
    cycle = eval_lines["NET_CYCLE"][0]
    assert has(cycle, "target_hits=2")
    assert has(cycle, "benign=0")
    assert "precision=1.00 recall=1.00" in cycle

    cover = {t: lines_for(lines, t, "accounts_new=") for t in TYPOLOGIES}
    assert all(len(v) == 1 for v in cover.values()), cover
    mule = cover["mule_ring"][0]
    for token in (
        "scenarios=1",
        "rule=1",
        "network=1",
        "new=0",
        "accounts=36",
        "accounts_rule=14",
        "accounts_network=29",
        "accounts_new=22",
    ):
        assert has(mule, token), (token, mule)
    assert has(cover["benign_merchant"][0], "network=0")
    for name, values in COVERAGE_EXPECTED.items():
        assert has(cover[name][0], f"scenarios={values[0]}"), name

    csv_lines = out.read_text(encoding="utf-8").splitlines()
    assert csv_lines[0] == ",".join(EVAL_COLUMNS)
    assert len([ln for ln in csv_lines[1:] if ln.strip()]) == 3


def test_ac9_cli_bad_as_of_exits_2_without_a_run(prepared: Path) -> None:
    before = _count(prepared, "SELECT COUNT(*) FROM monitoring_runs")
    result = _cli("network", "--as-of", "2026-13-01")
    assert result.exit_code == 2, result.output
    assert "No such command" not in result.output  # the command exists; the date is invalid
    assert _count(prepared, "SELECT COUNT(*) FROM monitoring_runs") == before == 6


def test_ac9_cli_search_budget_exceeded_exits_1_without_alerts(
    prepared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _count(prepared, "SELECT COUNT(*) FROM alerts")
    _set_env(monkeypatch, {"AML__NETWORK__CYCLES__MAX_SEARCH_STEPS": "11"})
    result = _cli("network")
    assert result.exit_code == 1, result.output
    assert "cycle search exceeded max_search_steps" in result.stderr
    assert _count(prepared, "SELECT COUNT(*) FROM alerts") == before == 31


def test_ac9_cli_without_er_fails_cleanly(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb").close()
    result = _cli("network")
    assert result.exit_code == 1, result.output
    assert "run `aml er` first" in result.stderr


def test_ac9_cli_without_load_fails_cleanly(
    tiny_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    with DuckDb(tmp_path / "tiny.duckdb") as db:
        mod("aml.dba.schema").apply_schema(db)
    result = _cli("network")
    assert result.exit_code == 1, result.output
    assert "run `aml load` first" in result.stderr
