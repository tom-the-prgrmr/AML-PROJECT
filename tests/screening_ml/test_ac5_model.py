"""AC5 for specs/screening-ml.md: the pure model on TOY and the comparison on PAIRS."""

from __future__ import annotations

import inspect
import json
import math
from typing import Any

import pytest

from .helpers import mod, pairs, settings_with, toy


def _model() -> Any:
    return mod("aml.screening.ml.model")


def _fit(**env: str) -> Any:
    X, y, groups, rule = toy()
    cfg = settings_with(**env).ml.screening
    return _model().fit_match_model(X, y, groups, rule, cfg, seed=42)


def test_ac5_fit_metrics_and_artifact() -> None:
    m = _fit()
    for key, want in {
        "n": 40, "n_true": 20, "n_false": 20, "prevalence": 0.5, "roc_auc": 1.0, "pr_auc": 1.0,
    }.items():  # fmt: skip
        assert m.metrics[key] == want, key
    assert m.params["class_weight"] == "balanced"
    assert m.params["cv_folds"] == 5
    assert m.params["seed"] == 42
    artifact = json.loads(m.artifact)
    assert set(artifact) == {"features", "mean", "scale", "coef", "intercept"}
    assert all(len(artifact[k]) == 19 for k in ("features", "mean", "scale", "coef"))
    assert len(m.data_hash) == 16


def test_ac5_predict_is_ranked_and_explained() -> None:
    X, *_ = toy()
    m = _fit()
    p = _model().predict(m, X)
    even = p["score"].iloc[0::2]
    odd = p["score"].iloc[1::2]
    assert even.min() > odd.max()
    intercept = json.loads(m.artifact)["intercept"]
    for score, contrib in zip(p["score"], p["contributions"], strict=True):
        z = intercept + sum(contrib.values())
        assert abs(1 / (1 + math.exp(-z)) - score) <= 1e-9
        assert max(contrib, key=lambda f: abs(contrib[f])) == "name_score"
        assert all(v == 0.0 for f, v in contrib.items() if f != "name_score")


def test_ac5_deterministic_and_hash_depends_on_data_not_order() -> None:
    first, second = _fit(), _fit()
    assert (first.artifact, first.metrics, first.data_hash) == (
        second.artifact, second.metrics, second.data_hash,
    )  # fmt: skip
    X, y, groups, rule = toy()
    cfg = settings_with().ml.screening
    rev = X.index[::-1]
    flipped = _model().fit_match_model(
        X.loc[rev], y.loc[rev], groups.loc[rev], rule.loc[rev], cfg, seed=42
    )
    assert flipped.data_hash == first.data_hash
    X.iloc[3, 4] += 0.5
    changed = _model().fit_match_model(X, y, groups, rule, cfg, seed=42)
    assert changed.data_hash != first.data_hash


def test_ac5_compare_at_recall_on_pairs() -> None:
    y, score, rule = pairs()
    df = _model().compare_at_recall(y, score, rule)
    assert list(df["baseline"]) == ["two_tier_alert", "two_tier"]
    cols = [
        "pairs", "positives", "rule_flagged", "rule_tp", "rule_precision", "rule_recall",
        "model_flagged", "model_tp", "model_precision", "model_recall", "flagged_reduction_pct",
    ]  # fmt: skip
    got = [tuple(df.iloc[i][cols]) for i in range(2)]
    assert got[0] == (10, 3, 4, 2, 0.5, 0.6667, 2, 2, 1.0, 0.6667, 50.0)
    assert got[1] == (10, 3, 6, 3, 0.5, 1.0, 3, 3, 1.0, 1.0, 50.0)


def test_ac5_compare_without_positives() -> None:
    y, score, rule = pairs()
    df = _model().compare_at_recall(y * 0, score, rule)
    row = df.iloc[0]
    assert row["rule_recall"] is None
    assert row["model_flagged"] == 0
    assert row["model_precision"] is None


def test_ac5_too_few_labelled_pairs() -> None:
    X, y, groups, rule = toy()
    y = y * 0
    y.iloc[[0, 2, 4, 6]] = 1
    cfg = settings_with().ml.screening
    with pytest.raises(
        _model().ScreeningMlError,
        match="not enough labelled pairs: need at least 5 per class, "
        "got TRUE_MATCH=4 FALSE_MATCH=36",
    ):
        _model().fit_match_model(X, y, groups, rule, cfg, seed=42)


def test_ac5_model_module_is_pure() -> None:
    source = inspect.getsource(_model())
    for banned in ("Database", "import duckdb", "record_review", "audit"):
        assert banned not in source, banned
