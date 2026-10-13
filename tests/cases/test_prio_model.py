"""AC4 and the pure half of AC7 for specs/case-prioritization.md: `aml.cases.model`.

TOY: 40 rows, ``network_alerts`` = 1 on even i, 0 on odd i, and nothing else separates the classes.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

import pandas as pd
import pytest

from .prio_helpers import (
    all_features,
    fit_toy,
    float_keys,
    is_even,
    logit_intercept,
    model_mod,
    prio_error,
    sigmoid,
    source_of,
    toy_config,
    toy_frame,
)

FRACTIONS = [0.1, 0.2, 0.5]


def test_ac4_logreg_cross_validated_metrics_on_toy() -> None:
    m, _, _, _ = fit_toy()
    assert m.kind == "logreg"
    assert tuple(m.features) == all_features()
    k = m.metrics
    assert (k["n"], k["n_suspicious"], k["n_false_positive"], k["prevalence"]) == (40, 20, 20, 0.5)
    assert k["roc_auc"] == 1.0
    assert k["pr_auc"] == 1.0
    assert float_keys(k["precision_at"]) == {0.1: 1.0, 0.2: 1.0, 0.5: 1.0}
    assert float_keys(k["recall_at"]) == {0.1: 0.2, 0.2: 0.4, 0.5: 1.0}
    assert float_keys(k["tail_false_positive_share"]) == {0.1: 0.2, 0.2: 0.4, 0.5: 1.0}
    assert float_keys(k["tail_suspicious"]) == {0.1: 0, 0.2: 0, 0.5: 0}
    assert m.params["class_weight"] == "balanced"
    assert m.params["cv_folds"] == 5


def test_ac4_artifact_layout() -> None:
    m, _, _, _ = fit_toy()
    artifact = json.loads(m.artifact)
    assert set(artifact) == {"features", "mean", "scale", "coef", "intercept"}
    assert tuple(artifact["features"]) == all_features()
    for key in ("mean", "scale", "coef"):
        assert len(artifact[key]) == 35, key


def test_ac4_predict_scores_and_additive_contributions() -> None:
    m, X, _, _ = fit_toy()
    p = model_mod().predict(m, X)
    assert list(p.index) == list(X.index)
    assert {"score", "contributions"} <= set(p.columns)
    intercept = logit_intercept(m.artifact)
    for case_id, row in p.iterrows():
        assert (row["score"] > 0.5) == is_even(str(case_id)), case_id
        contributions = row["contributions"]
        assert set(contributions) == set(all_features())
        total = intercept + sum(contributions.values())
        assert abs(float(sigmoid(total)) - row["score"]) <= 1e-9, case_id
        top = max(contributions, key=lambda f: abs(contributions[f]))
        assert top == "network_alerts", case_id
        assert contributions["has_net_hub"] == 0.0  # constant feature: no contribution


def test_ac4_fit_is_deterministic_and_the_hash_covers_the_data_not_the_order() -> None:
    first, X, y, groups = fit_toy()
    second, _, _, _ = fit_toy()
    assert (first.artifact, first.metrics, first.data_hash) == (
        second.artifact,
        second.metrics,
        second.data_hash,
    )
    assert re.fullmatch(r"[0-9a-f]{16}", first.data_hash)

    order = list(reversed(X.index))
    shuffled = model_mod().fit_model(
        X.loc[order], y.loc[order], groups.loc[order], toy_config(), seed=42
    )
    assert shuffled.data_hash == first.data_hash

    changed = X.copy()
    changed.iloc[0, changed.columns.get_loc("alerts")] += 1.0
    other = model_mod().fit_model(changed, y, groups, toy_config(), seed=42)
    assert other.data_hash != first.data_hash


def test_ac4_ranking_metrics_perfect_ranking() -> None:
    k = model_mod().ranking_metrics(pd.Series([1, 1, 0, 0]), pd.Series([0.9, 0.8, 0.7, 0.1]), [0.5])
    assert float_keys(k["precision_at"]) == {0.5: 1.0}
    assert float_keys(k["recall_at"]) == {0.5: 1.0}
    assert k["roc_auc"] == 1.0


def test_ac4_ranking_metrics_head_and_tail_by_the_rules() -> None:
    # order by score: i0 (1), i2 (0), i1 (1), i3 (0)
    y = pd.Series([1, 1, 0, 0])
    score = pd.Series([0.9, 0.2, 0.8, 0.1])
    k = model_mod().ranking_metrics(y, score, [0.25, 0.5])
    assert (k["n"], k["n_suspicious"], k["n_false_positive"], k["prevalence"]) == (4, 2, 2, 0.5)
    assert k["roc_auc"] == 0.75
    assert float_keys(k["precision_at"]) == {0.25: 1.0, 0.5: 0.5}
    assert float_keys(k["recall_at"]) == {0.25: 0.5, 0.5: 0.5}
    assert float_keys(k["tail_false_positive_share"]) == {0.25: 0.5, 0.5: 0.5}
    assert float_keys(k["tail_suspicious"]) == {0.25: 0, 0.5: 1}


def test_ac4_ranking_metrics_tie_goes_to_the_smaller_case_id() -> None:
    y = pd.Series([0, 1], index=["b", "a"])
    k = model_mod().ranking_metrics(y, pd.Series([0.5, 0.5], index=["b", "a"]), [0.5])
    assert float_keys(k["precision_at"]) == {0.5: 1.0}  # "a" ranks first
    assert float_keys(k["recall_at"]) == {0.5: 1.0}


def test_ac4_ranking_metrics_with_one_class_has_no_auc() -> None:
    k = model_mod().ranking_metrics(pd.Series([1, 1, 1, 1]), pd.Series([0.9, 0.8, 0.7, 0.1]), [0.5])
    assert k["roc_auc"] is None
    assert k["pr_auc"] is None
    assert k["prevalence"] == 1.0
    assert float_keys(k["tail_false_positive_share"]) == {0.5: None}


def test_ac4_one_class_is_refused() -> None:
    X, _, groups = toy_frame()
    with pytest.raises(
        prio_error(),
        match=re.escape("need at least 5 per class, got SUSPICIOUS=40 FALSE_POSITIVE=0"),
    ):
        model_mod().fit_model(X, pd.Series(1, index=X.index), groups, toy_config(), seed=42)


def test_ac4_four_false_positives_are_too_few() -> None:
    X, _, groups = toy_frame()
    few = pd.Series(1, index=X.index)
    few.iloc[[1, 3, 5, 7]] = 0
    with pytest.raises(prio_error(), match="FALSE_POSITIVE=4"):
        model_mod().fit_model(X, few, groups, toy_config(), seed=42)


def test_ac4_model_module_is_pure() -> None:
    source = source_of("aml.cases.model")
    for forbidden in ("import duckdb", "Database", "record_disposition"):
        assert forbidden not in source, forbidden


# ------------------------------------------------------------------ AC7: LightGBM, pure part
def _lightgbm_toy() -> tuple[Any, pd.DataFrame]:
    pytest.importorskip("lightgbm")
    m, X, _, _ = fit_toy(kind="lightgbm")
    return m, X


def test_ac7_lightgbm_model_on_toy() -> None:
    m, X = _lightgbm_toy()
    assert m.kind == "lightgbm"
    assert m.metrics["roc_auc"] == 1.0
    assert m.params["class_weight"] == "balanced"
    assert isinstance(m.artifact, str)
    assert m.artifact.startswith("tree")
    p = model_mod().predict(m, X)
    even = [s for i, s in zip(p.index, p["score"], strict=True) if is_even(str(i))]
    odd = [s for i, s in zip(p.index, p["score"], strict=True) if not is_even(str(i))]
    assert min(even) > max(odd)
    for contributions in p["contributions"]:
        assert max(contributions, key=lambda f: abs(contributions[f])) == "network_alerts"


def test_ac7_lightgbm_fit_is_deterministic() -> None:
    first, _ = _lightgbm_toy()
    second, _, _, _ = fit_toy(kind="lightgbm")
    assert first.artifact == second.artifact


def test_ac7_missing_lightgbm_is_a_clear_error_and_logreg_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    X, y, groups = toy_frame()
    monkeypatch.setitem(sys.modules, "lightgbm", None)
    with pytest.raises(
        prio_error(), match=re.escape("lightgbm is not installed: uv sync --extra ml")
    ):
        model_mod().fit_model(X, y, groups, toy_config(), seed=42, kind="lightgbm")
    assert (
        model_mod().fit_model(X, y, groups, toy_config(), seed=42, kind="logreg").kind == "logreg"
    )
