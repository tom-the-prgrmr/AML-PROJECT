"""AC6 for specs/ml-governance.md: `aml cases btl` and the `aml score` chain with the sample."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import get_settings
from aml.common.db import DuckDb
from tests.cases.helpers import has
from tests.cases.prio_helpers import make_tiny_l

from .helpers import BTL_LAST_LINE, PINNED, SAMPLE, SIMULATE, cli

ENABLED = "AML__CASES__PRIORITIZATION__BELOW_THE_LINE__ENABLED"
NOTE_START = "note metrics cover alerted cases only; below-the-line sample: run"
RANKING_ONLY = "ranking only: no case was closed or cleared by the model"
UseStage = Callable[[str], Path]


def _starting(output: str, word: str) -> list[str]:
    return [ln for ln in output.splitlines() if ln.split(" ")[0] == word]


def _tiny_l(cli_db: UseStage, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = cli_db("full")
    monkeypatch.setenv(SIMULATE, "false")
    for key, value in PINNED.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    with DuckDb(path) as db:
        make_tiny_l(db, get_settings(), final_run=False)
    return path


def test_ac6_the_command_chain(
    cli_db: UseStage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _tiny_l(cli_db, monkeypatch)

    # 1. the sample is drawn and printed; no model yet, so nothing is measured
    out = tmp_path / "btl.json"
    first = cli("cases", "btl", "--size", "50", "--eval-out", str(out))
    assert first.exit_code == 0, first.output + first.stderr
    (line,) = _starting(first.stdout, "btl")
    for token in (
        "population=221",
        "size=50",
        "suspicious=3",
        "estimated_missed=13",
        "reused=False",
    ):
        assert has(line, token), (token, line)
    assert "ci95=0.0206-0.1622" in line
    (skipped,) = _starting(first.stdout, "btl-eval")
    assert (
        skipped.startswith("btl-eval skipped:")
        and "no model: run `aml cases train` first" in skipped
    )
    assert first.stdout.splitlines()[-1] == BTL_LAST_LINE
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert set(payload) == {"sample", "evaluation"} and payload["sample"]["population"] == 221

    # 2. --train: the variant is model 1 (the sample is reused)
    train = cli("cases", "btl", "--size", "50", "--train")
    assert train.exit_code == 0, train.output + train.stderr
    assert has(_starting(train.stdout, "btl")[0], "reused=True")
    (model,) = _starting(train.stdout, "model")
    assert "version=prio/logreg+btl/1" in model
    (by_population,) = _starting(train.stdout, "by-population")
    assert "alerted n=38" in by_population and "below_the_line n=50" in by_population
    measured = [
        ln for ln in _starting(train.stdout, "btl-eval") if ln.startswith("btl-eval model=")
    ]
    (evaluation,) = measured
    assert evaluation.startswith("btl-eval model=prio/logreg+btl/1")
    assert has(evaluation, "n=50") and has(evaluation, "prevalence=0.06")
    assert train.stdout.splitlines()[-1] == BTL_LAST_LINE

    # 3. aml score with the default configuration: the 7c chain, the model is prio/logreg/2
    score = cli("score", "--top", "3")
    assert score.exit_code == 0, score.output + score.stderr
    assert _starting(score.stdout, "btl") == [] and _starting(score.stdout, "btl-eval") == []
    (model,) = _starting(score.stdout, "model")
    assert "version=prio/logreg/2" in model and "+btl" not in model
    lines = score.stdout.splitlines()
    assert lines[-2].startswith(NOTE_START) and lines[-1] == RANKING_ONLY

    # 4. aml score with the sample switched on: the variant is model 3, a sample of the new run
    monkeypatch.setenv(ENABLED, "true")
    monkeypatch.setenv(SAMPLE, "50")
    get_settings.cache_clear()
    prio_out = tmp_path / "prio.json"
    on = cli("score", "--top", "3", "--eval-out", str(prio_out))
    assert on.exit_code == 0, on.output + on.stderr
    (model,) = _starting(on.stdout, "model")
    assert "version=prio/logreg+btl/3" in model
    assert len(_starting(on.stdout, "btl")) == 1
    (evaluation,) = _starting(on.stdout, "btl-eval")
    assert evaluation.startswith("btl-eval model=prio/logreg+btl/3")
    order = [ln.split(" ")[0] for ln in on.stdout.splitlines()]
    assert (
        order.index("btl") < order.index("model") < order.index("holdout") < order.index("btl-eval")
    )
    assert on.stdout.splitlines()[-1] == RANKING_ONLY
    body: dict[str, Any] = json.loads(prio_out.read_text(encoding="utf-8"))
    assert set(body) == {"model", "cv", "holdout", "below_the_line"}


def test_ac6_option_errors(cli_db: UseStage, monkeypatch: pytest.MonkeyPatch) -> None:
    cli_db("load")
    monkeypatch.setenv(SAMPLE, "50")
    get_settings.cache_clear()
    assert cli("cases", "btl", "--model", "xgboost").exit_code == 2
    assert cli("cases", "btl", "--size", "0").exit_code == 2
    result = cli("cases", "btl")  # only `aml load` was run: there is no case run yet
    assert result.exit_code == 1
    assert "run `aml cases build` first" in result.stderr
