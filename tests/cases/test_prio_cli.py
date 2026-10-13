"""AC8 for specs/case-prioritization.md: `aml score`, `aml cases label`, `aml cases train`.

Two states are used. TINY after the three alert sources (no labels: one class only) and TINY-L
with the 38 decisions recorded on run 1 and the simulation switched off by
`AML__CASES__PRIORITIZATION__SIMULATE_DISPOSITIONS=false`, so that the `run_cases` inside
`aml score` is the run that closes the 38 cases (`closed=38`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from aml.common.config import get_settings
from aml.common.db import DuckDb

from .helpers import cli, count, has, mod
from .prio_helpers import make_tiny_l

UseStage = Callable[[str], Path]
SIMULATE = "AML__CASES__PRIORITIZATION__SIMULATE_DISPOSITIONS"
LAST = "ranking only: no case was closed or cleared by the model"


def _starting(output: str, word: str) -> list[str]:
    return [ln for ln in output.splitlines() if ln.split(" ")[0] == word]


def _tiny_l(cli_db: UseStage, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = cli_db("full")
    monkeypatch.setenv(SIMULATE, "false")
    get_settings.cache_clear()
    with DuckDb(path) as db:
        make_tiny_l(db, get_settings(), final_run=False)
    return path


def _counts(path: Path, *tables: str) -> list[int]:
    with DuckDb(path) as db:
        mod("aml.dba.schema").apply_schema(db)  # idempotent; makes sure the tables exist
        return [count(db, t) for t in tables]


def test_ac8_one_class_stops_at_training_but_keeps_the_earlier_steps(cli_db: UseStage) -> None:
    path = cli_db("sources")
    result = cli("score")
    assert result.exit_code == 1, result.output
    assert any(has(ln, "cases=52") for ln in _starting(result.stdout, "cases"))
    labels = _starting(result.stdout, "labels")
    assert len(labels) == 1 and has(labels[0], "FALSE_POSITIVE=0")
    assert "not enough labelled cases" in result.stderr
    assert _counts(path, "case_models", "case_scores") == [0, 0]
    with DuckDb(path) as db:
        assert count(db, "case_runs") == 2  # build, simulate, build again
        assert count(db, "case_dispositions") > 0
        assert count(db, "case_dispositions", "WHERE origin <> 'SIMULATED'") == 0


def test_ac8_score_runs_the_whole_chain_on_tiny_l(
    cli_db: UseStage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _tiny_l(cli_db, monkeypatch)
    out = tmp_path / "prio.json"
    result = cli("score", "--top", "3", "--eval-out", str(out))
    assert result.exit_code == 0, result.output + result.stderr
    lines = result.stdout.splitlines()

    cases = _starting(result.stdout, "cases")
    assert len(cases) == 1
    assert has(cases[0], "cases=52") and has(cases[0], "closed=38")
    assert _starting(result.stdout, "labels") == []
    model = _starting(result.stdout, "model")
    assert len(model) == 1
    assert "version=prio/logreg/1" in model[0] and has(model[0], "cases=38")
    assert "prevalence=0.71" in model[0]
    scored = _starting(result.stdout, "scored")
    assert len(scored) == 1
    assert has(scored[0], "cases=52") and has(scored[0], "queue=14")
    assert "model=prio/logreg/1" in scored[0]
    holdout = _starting(result.stdout, "holdout")
    assert len(holdout) == 1 and has(holdout[0], "n=14")

    ranked = [ln for ln in lines if ln.split(" ")[0].isdigit()]
    assert [ln.split(" ")[0] for ln in ranked] == ["1", "2", "3"]
    assert all("top=" in ln for ln in ranked)
    assert lines[-1] == LAST

    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"model", "cv", "holdout"}
    assert data["model"]["version"] == "prio/logreg/1"
    assert data["cv"]["n"] == 38


def test_ac8_train_and_label_follow_up_on_the_same_database(
    cli_db: UseStage, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _tiny_l(cli_db, monkeypatch)
    assert cli("score").exit_code == 0

    trained = cli("cases", "train")
    assert trained.exit_code == 0, trained.output + trained.stderr
    assert "version=prio/logreg/2" in trained.stdout

    labelled = cli("cases", "label", "--fraction", "1.0")
    assert labelled.exit_code == 0, labelled.output + labelled.stderr
    assert has(labelled.stdout, "labelled=14") and has(labelled.stdout, "skipped=38")
    with DuckDb(path) as db:
        assert count(db, "case_dispositions", "WHERE origin = 'SIMULATED'") == 14


def test_ac8_bad_arguments_exit_2(cli_db: UseStage) -> None:
    cli_db("sources")
    # the options exist (an unknown command or option would also exit 2)
    assert "--model" in cli("cases", "train", "--help").stdout
    assert "--as-of" in cli("score", "--help").stdout
    assert cli("cases", "train", "--model", "xgboost").exit_code == 2
    assert cli("score", "--as-of", "2026-13-01").exit_code == 2


def test_ac8_score_is_listed_and_no_command_is_a_stub(cli_db: UseStage) -> None:
    assert "score" in cli("--help").stdout
    cli_db("sources")
    for args in (("score",), ("cases", "label"), ("cases", "train")):
        result = cli(*args)
        assert "arrives in Phase 7" not in result.stdout + result.stderr, args


def test_ac8_without_entity_resolution_the_chain_stops_at_the_first_step(
    cli_db: UseStage,
) -> None:
    cli_db("load")
    result = cli("score")
    assert result.exit_code == 1, result.output
    assert "run `aml er` first" in result.stderr
