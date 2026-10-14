"""AC4 for specs/ml-governance.md: the active model measured on the below-the-line sample."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from aml.cases.model import predict

from .helpers import (
    audit_df,
    btl,
    btl_model,
    build_tiny_b,
    build_tiny_l,
    counts,
    js,
    prio,
    prio_error,
    prio_store,
    query,
)

GUARDED = ("case_scores", "case_models", "case_dispositions", "cases")


@pytest.fixture(scope="module")
def state(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[SimpleNamespace]:
    db, settings = build_tiny_l(tiny_stages, tmp_path_factory)
    prio().train(db, settings, actor="analyst01")
    before = counts(db, *GUARDED)
    first = btl_model().evaluate_btl(db, settings, actor="analyst01")
    second = btl_model().evaluate_btl(db, settings, actor="analyst01")
    yield SimpleNamespace(
        db=db, settings=settings, first=first, second=second, before=before,
        after=counts(db, *GUARDED),
    )  # fmt: skip
    db.close()


def test_ac4_metrics_of_the_sample(state: SimpleNamespace) -> None:
    e = state.first
    assert (e.model_id, e.version) == (1, "prio/logreg/1")
    m = e.metrics
    assert (m["n"], m["n_suspicious"], m["n_false_positive"]) == (50, 3, 47)
    assert m["prevalence"] == 0.06
    assert (m["population"], m["estimated_missed"]) == (221, 13)
    assert m["prevalence_ci95"] == [0.0206, 0.1622]
    for name in ("roc_auc", "pr_auc"):
        assert 0.0 <= m[name] <= 1.0


def test_ac4_stored_scores_are_the_models_scores(state: SimpleNamespace) -> None:
    db, e = state.db, state.first
    rows = query(db, f"SELECT * FROM btl_evaluations WHERE eval_id = {e.eval_id}")
    assert len(rows) == 1 and rows["model_version"].iloc[0] == "prio/logreg/1"
    scores = js(rows["scores"].iloc[0])
    sample = btl().draw_sample(db, state.settings)
    assert sorted(scores) == [m.golden_customer_id for m in sample.members]
    _, _, model = prio_store().read_model(db, 1)
    X = btl().read_btl_features(db, state.settings, sample.sample_id)
    expected = predict(model, X)["score"]
    assert max(abs(scores[g] - expected[g]) for g in scores) <= 1e-6
    assert js(rows["metrics"].iloc[0]) == e.metrics


def test_ac4_audit_row_carries_the_model_version(state: SimpleNamespace) -> None:
    rows = audit_df(state.db, "decision = 'BTL_EVALUATED'")
    assert len(rows) == 2
    a = rows.iloc[0]
    assert (a["module"], a["entity_type"], a["entity_id"]) == ("cases", "model", "prio/logreg/1")
    assert (a["version"], a["actor"]) == ("prio/logreg/1", "analyst01")
    assert a["reason"].startswith("measured prio/logreg/1 on below-the-line sample")
    assert a["reason"].endswith("measurement only")
    assert a["details"]["eval_id"] == state.first.eval_id


def test_ac4_a_second_evaluation_reuses_the_sample(state: SimpleNamespace) -> None:
    assert state.second.eval_id != state.first.eval_id
    assert state.second.metrics == state.first.metrics
    assert state.second.sample_id == state.first.sample_id
    assert int(query(state.db, "SELECT COUNT(*) AS n FROM btl_samples")["n"].iloc[0]) == 1


def test_ac4_nothing_of_the_queue_changes(state: SimpleNamespace) -> None:
    assert state.before == state.after


def test_ac4_no_model_is_an_error_before_any_write(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    db, settings = build_tiny_b(tiny_stages, tmp_path_factory)
    try:
        with pytest.raises(prio_error(), match="no model: run `aml cases train` first"):
            btl_model().evaluate_btl(db, settings)
        assert counts(db, "btl_samples", "btl_evaluations") == [0, 0]
    finally:
        db.close()
