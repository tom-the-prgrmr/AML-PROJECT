"""AC6 for specs/screening-ml.md: `train` stores the model, its training set and an audit row."""

from __future__ import annotations

import json
from typing import Any

import pytest
import sklearn

from aml.common.db import DuckDb

from .helpers import audit_df, mod, query, scalar, settings_with, snapshot

FULL = {"AML__ML__SCREENING__SIMULATE_FRACTION": "1.0"}


def _pipeline() -> Any:
    return mod("aml.screening.ml.pipeline")


def _labelled(db: DuckDb, **env: str) -> None:
    mod("aml.screening.ml.labels").simulate_labels(db, settings_with(**{**FULL, **env}))


def test_ac6_train_stores_model_training_and_audit(tiny_s: DuckDb) -> None:
    _labelled(tiny_s)
    s = settings_with(**FULL)
    results = snapshot(tiny_s, "screening_results", "run_id, cif, entry_id")
    labels = snapshot(tiny_s, "screening_ml_labels", "label_id")
    t = _pipeline().train(tiny_s, s, actor="analyst01")
    assert (t.model_id, t.version) == (1, "scrml/logreg/1")
    assert (t.pairs, t.true_match, t.false_match, t.human_labels) == (55, 5, 50, 0)
    assert t.metrics["prevalence"] == 0.0909
    alert = t.metrics["comparison"][0]
    assert alert["baseline"] == "two_tier_alert"
    assert (alert["rule_flagged"], alert["rule_tp"], alert["model_flagged"]) == (5, 5, 5)
    assert alert["model_precision"] == 1.0

    models = query(tiny_s, "SELECT * FROM screening_ml_models")
    assert len(models) == 1
    row = models.iloc[0]
    assert (row["version"], row["kind"], row["feature_version"]) == (
        "scrml/logreg/1", "logreg", "screening-ml-features/v1",
    )  # fmt: skip
    assert (row["seed"], row["pairs"], row["actor"]) == (42, 55, "analyst01")
    assert json.loads(row["features"]) == list(mod("aml.screening.ml.features").FEATURES)
    assert json.loads(row["params"])["sklearn"] == sklearn.__version__
    assert len(row["data_hash"]) == 16
    int(row["data_hash"], 16)

    training = query(tiny_s, "SELECT * FROM screening_ml_training")
    assert len(training) == 55
    assert set(training["model_id"]) == {1}
    assert int(training["label"].sum()) == 5
    assert set(training["origin"]) == {"SIMULATED"}

    trained = audit_df(tiny_s, "module = 'screening_ml' AND decision = 'MODEL_TRAINED'")
    assert len(trained) == 1
    a = trained.iloc[0]
    assert (a["entity_id"], a["version"], a["actor"]) == (
        "scrml/logreg/1",
        "scrml/logreg/1",
        "analyst01",
    )
    assert a["reason"].startswith(
        "trained logreg on 55 labelled screening pairs "
        "(5 TRUE_MATCH, 50 FALSE_MATCH, 0 from human reviews; class_weight balanced)"
    )
    assert a["reason"].endswith("ranking only")
    assert a["details"]["data_hash"] == row["data_hash"]

    again = _pipeline().train(tiny_s, s, actor="analyst01")
    assert again.model_id == 2
    assert again.metrics == t.metrics
    second = query(tiny_s, "SELECT * FROM screening_ml_models WHERE model_id = 2").iloc[0]
    assert (second["artifact"], second["data_hash"]) == (row["artifact"], row["data_hash"])
    assert scalar(tiny_s, "SELECT model_id FROM screening_ml_model_active") == 2
    assert snapshot(tiny_s, "screening_results", "run_id, cif, entry_id") == results
    assert snapshot(tiny_s, "screening_ml_labels", "label_id") == labels


def test_ac6_too_few_true_matches_stores_no_model(tiny_s: DuckDb) -> None:
    _labelled(tiny_s, AML__ML__SCREENING__SIMULATE_FRACTION="0.7")
    error = mod("aml.screening.ml.model").ScreeningMlError
    with pytest.raises(error, match="got TRUE_MATCH=4 FALSE_MATCH=35"):
        _pipeline().train(tiny_s, settings_with())
    assert scalar(tiny_s, "SELECT COUNT(*) FROM screening_ml_models") == 0
    assert scalar(tiny_s, "SELECT COUNT(*) FROM screening_ml_training") == 0
