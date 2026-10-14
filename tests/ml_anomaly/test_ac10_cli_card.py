"""AC10 for specs/ml-anomaly.md: `aml anomaly run` / `eval` and `card_facts` on TINY."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from aml.common.config import get_settings
from aml.common.db import DuckDb
from aml.datagen.activity import TYPOLOGY_KEYS
from tests.cases.helpers import cli

from .helpers import CLI_LINE_END, card

UseStage = Callable[[str], Path]
EVAL_KEYS = {
    "command", "run_id", "model_version", "as_of", "samples", "alerts", "alert_top_fraction",
    "threshold", "suspicious", "benign", "alerts_by_kind", "alerts_on_rule_alerted_customers",
    "coverage",
}  # fmt: skip
CARD_KEYS = {
    "model", "data", "features", "params", "metrics", "alerts", "evaluation", "limitations", "use",
}  # fmt: skip


def test_ac10_eval_before_any_run_fails(cli_db: UseStage) -> None:
    cli_db("full")
    result = cli("anomaly", "eval")
    assert result.exit_code == 1
    assert "no anomaly run yet: run `aml anomaly run` first" in result.stderr


def test_ac10_run_prints_the_summary_and_the_coverage(cli_db: UseStage) -> None:
    cli_db("full")
    result = cli("anomaly", "run")
    assert result.exit_code == 0, result.output + result.stderr
    lines = result.stdout.splitlines()
    summary = [ln for ln in lines if "run_id=" in ln]
    assert len(summary) == 1
    for token in ("model_version=anomaly/v1/", "samples=1334", "alerts=7", "graph_source=networkx"):
        assert token in summary[0], token
    typology = [ln for ln in lines if ln.split(" ")[0] in TYPOLOGY_KEYS]
    assert [ln.split(" ")[0] for ln in typology] == list(TYPOLOGY_KEYS)
    for ln in typology:
        for token in ("scenarios=", "rules=", "anomaly=", "new=", "accounts_new="):
            assert token in ln, (ln, token)
    assert lines[-1] == CLI_LINE_END


def test_ac10_as_of_option_cuts_the_months(cli_db: UseStage) -> None:
    cli_db("full")
    result = cli("anomaly", "run", "--as-of", "2026-05-31")
    assert result.exit_code == 0, result.output + result.stderr
    summary = next(ln for ln in result.stdout.splitlines() if "run_id=" in ln)
    assert "as_of=2026-05-31" in summary and "months=5" in summary


def test_ac10_eval_files_and_default_path(
    cli_db: UseStage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = cli_db("full")
    results = tmp_path / "results"
    monkeypatch.setenv("AML__ML__ANOMALY__RESULTS_DIR", str(results))
    get_settings.cache_clear()
    assert cli("anomaly", "run").exit_code == 0
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert cli("anomaly", "run", "--eval-out", str(a)).exit_code == 0
    assert cli("anomaly", "eval", "--eval-out", str(b)).exit_code == 0
    first, second = json.loads(a.read_text("utf-8")), json.loads(b.read_text("utf-8"))
    assert set(first) == set(second) == EVAL_KEYS
    assert first["command"].startswith("aml anomaly run --eval-out")
    assert second["command"].startswith("aml anomaly eval --eval-out")
    with DuckDb(path) as db:
        latest = int(db.query_df("SELECT MAX(run_id) FROM anomaly_runs").iloc[0, 0])
    assert second["run_id"] == first["run_id"] == latest == 2
    assert not (results / "anomaly_eval.json").exists()  # run without --eval-out writes nothing
    assert cli("anomaly", "eval").exit_code == 0
    default = json.loads((results / "anomaly_eval.json").read_text("utf-8"))
    assert set(default) == EVAL_KEYS and default["command"].startswith("aml anomaly eval")


def test_ac10_run_on_a_database_without_data_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DB_BACKEND", "duckdb")
    monkeypatch.setenv("AML__DB__DUCKDB_PATH", str(tmp_path / "empty.duckdb"))
    get_settings.cache_clear()
    assert cli("init-db").exit_code == 0
    result = cli("anomaly", "run")
    assert result.exit_code == 1
    assert "transactions is empty; run `aml load` first" in result.stderr


def test_ac10_card_facts(cli_db: UseStage) -> None:
    path = cli_db("full")
    assert cli("anomaly", "run").exit_code == 0
    assert cli("anomaly", "run").exit_code == 0
    settings = get_settings()
    with DuckDb(path) as db:
        facts = card().card_facts(db, settings)
        first = card().card_facts(db, settings, run_id=1)
    assert set(facts) == CARD_KEYS
    assert facts["model"]["version"] == "anomaly/v1/2"
    assert facts["model"]["name"] == "ml-anomaly" and facts["model"]["kind"] == "isolation_forest"
    assert facts["data"]["synthetic"] is True
    assert len(facts["features"]) == 14
    assert all(f["doc"] for f in facts["features"])
    assert facts["use"]["auto_close"] is False
    assert len(facts["limitations"]) >= 6
    assert facts["alerts"]["count"] == 7 and facts["evaluation"]["run_id"] == 2
    assert first["model"]["version"] == "anomaly/v1/1"
    assert first["evaluation"]["run_id"] == 1
