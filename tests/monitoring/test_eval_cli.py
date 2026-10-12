"""AC9 for specs/monitoring-rules.md: evaluation against ground truth and `aml monitor`."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aml.common.config import Settings, get_settings
from aml.common.db import DuckDb

from .helpers import (
    EVAL_COLUMNS,
    EVAL_EXPECTED,
    EVAL_VALUE_COLUMNS,
    RULE_IDS,
    duck_settings,
    load_tiny_duck,
    mod,
    none_if_nan,
    run_monitoring,
    scalar,
)

TYPOLOGIES = [
    "structuring",
    "rapid_movement",
    "mule_ring",
    "round_tripping",
    "benign_payroll",
    "benign_merchant",
]


@pytest.fixture(scope="module")
def once(tiny_parquet: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[DuckDb]:
    db = load_tiny_duck(tiny_parquet, tmp_path_factory.mktemp("mon_eval") / "tiny.duckdb")
    settings: Settings = duck_settings()
    run_monitoring(db, settings)
    yield db
    db.close()


def _cli(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, list(args))


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def _count(path: Path, sql: str) -> int:
    with DuckDb(path) as db:
        return int(scalar(db, sql))


def _has(line: str, token: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(token)}(?![\w.])", line) is not None


def _lines_for(lines: list[str], name: str, marker: str) -> list[str]:
    return [ln for ln in lines if ln.lstrip().startswith(name) and marker in ln]


# ----------------------------------------------------------------------------- AC9 evaluation
def test_ac9_evaluate_rules(once: DuckDb) -> None:
    df = mod("aml.monitoring.evaluate").evaluate_rules(once)
    df.columns = [c.lower() for c in df.columns]
    assert list(df.columns) == EVAL_COLUMNS
    assert list(df["rule_id"]) == list(RULE_IDS)
    for row in df.itertuples():
        expected = EVAL_EXPECTED[row.rule_id]
        actual = tuple(none_if_nan(getattr(row, c)) for c in EVAL_VALUE_COLUMNS)
        assert len(actual) == len(expected)
        for col, got, want in zip(EVAL_VALUE_COLUMNS, actual, expected, strict=True):
            if want is None:
                assert got is None, (row.rule_id, col, got)
            else:
                assert got == pytest.approx(want), (row.rule_id, col, got)


def test_ac9_evaluate_rules_target_typology_column(once: DuckDb) -> None:
    df = mod("aml.monitoring.evaluate").evaluate_rules(once)
    df.columns = [c.lower() for c in df.columns]
    assert [none_if_nan(v) for v in df["target_typology"]] == [
        "structuring",
        "rapid_movement",
        None,
        "mule_ring",
        "mule_ring",
        None,
    ]


def test_ac9_typology_coverage(once: DuckDb) -> None:
    df = mod("aml.monitoring.evaluate").typology_coverage(once)
    df.columns = [c.lower() for c in df.columns]
    assert list(df.columns) == [
        "typology",
        "is_suspicious",
        "scenarios",
        "flagged",
        "rate",
        "rules",
    ]
    assert list(df["typology"]) == TYPOLOGIES
    rows = {r.typology: r for r in df.itertuples()}
    expected = {
        "structuring": (2, 2, 1.0),
        "rapid_movement": (2, 2, 1.0),
        "mule_ring": (1, 1, 1.0),
        "round_tripping": (2, 2, 1.0),
        "benign_payroll": (1, 0, 0.0),
        "benign_merchant": (1, 0, 0.0),
    }
    for name, (scenarios, flagged, rate) in expected.items():
        r = rows[name]
        assert (int(r.scenarios), int(r.flagged)) == (scenarios, flagged), name
        assert float(r.rate) == pytest.approx(rate), name
    assert [bool(v) for v in df["is_suspicious"]] == [True] * 4 + [False] * 2
    assert rows["round_tripping"].rules == "RAPID_MOVEMENT"
    assert rows["mule_ring"].rules == (
        "DORMANT_REACTIVATION,FAN_IN,FAN_OUT,HIGH_VELOCITY,RAPID_MOVEMENT"
    )
    assert rows["benign_payroll"].rules == ""
    assert rows["benign_merchant"].rules == ""


# ----------------------------------------------------------------------------- AC9 CLI
def test_ac9_cli_monitor_prints_rules_summary_eval_and_csv(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb").close()
    out = tmp_path / "monitoring_eval.csv"

    result = _cli("monitor", "--eval-out", str(out))
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()

    rule_lines = {r: _lines_for(lines, r, "evidence=") for r in RULE_IDS}
    assert all(len(v) == 1 for v in rule_lines.values()), rule_lines
    assert _has(rule_lines["STRUCTURING"][0], "alerts=2")
    assert _has(rule_lines["STRUCTURING"][0], "evidence=14")
    assert _has(rule_lines["DORMANT_REACTIVATION"][0], "alerts=13")
    assert _has(rule_lines["DORMANT_REACTIVATION"][0], "evidence=55")

    summary = [ln for ln in lines if "run_id=1" in ln]
    assert any(
        all(_has(ln, t) for t in ("run_id=1", "as_of=2026-06-30", "alerts=31", "evidence=323"))
        for ln in summary
    ), summary

    eval_lines = {r: _lines_for(lines, r, "target_hits=") for r in RULE_IDS}
    assert all(len(v) == 1 for v in eval_lines.values()), eval_lines
    rapid = eval_lines["RAPID_MOVEMENT"][0]
    for token in ("target_hits=2", "other_suspicious=3", "benign=0"):
        assert _has(rapid, token), token
    assert "precision=0.40 recall=1.00" in rapid
    assert "precision=n/a recall=n/a" in eval_lines["HIGH_VELOCITY"][0]

    cover = {t: _lines_for(lines, t, "flagged=") for t in TYPOLOGIES}
    assert all(len(v) == 1 for v in cover.values()), cover
    assert "scenarios=1 flagged=0" in cover["benign_payroll"][0]

    csv_lines = out.read_text(encoding="utf-8").splitlines()
    assert csv_lines[0] == ",".join(EVAL_COLUMNS)
    assert len([ln for ln in csv_lines[1:] if ln.strip()]) == 6


def test_ac9_cli_bad_as_of_exits_2_without_a_run(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    path = tmp_path / "tiny.duckdb"
    load_tiny_duck(tiny_parquet, path).close()
    assert _cli("monitor").exit_code == 0
    before = _count(path, "SELECT COUNT(*) FROM monitoring_runs")
    result = _cli("monitor", "--as-of", "2026-13-01")
    assert result.exit_code == 2, result.output
    assert _count(path, "SELECT COUNT(*) FROM monitoring_runs") == before == 6


def test_ac9_cli_without_load_fails_cleanly(
    tiny_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    with DuckDb(tmp_path / "tiny.duckdb") as db:
        mod("aml.dba.schema").apply_schema(db)
    result = _cli("monitor")
    assert result.exit_code == 1, result.output
    assert "run `aml load` first" in result.stderr
