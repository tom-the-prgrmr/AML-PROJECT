"""Fixes after the independent review of Phase 7c (specs/case-prioritization.md): small fixtures."""

from __future__ import annotations

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import CASE_C04, duck_settings, load_minic, mod, query, run_cases
from .helpers import record_disposition as dispose
from .prio_helpers import (
    FRACTION,
    MINI_TRUTH,
    insert_truth,
    labels_mod,
    minigt,
    model_mod,
    prio_error,
    prio_mod,
    toy_config,
    toy_frame,
)
from .supp_helpers import STATE_ROWS


def _disposed(db: DuckDb) -> set[str]:
    return set(query(db, "SELECT case_id FROM case_dispositions")["case_id"])


def test_a_simulating_twice_with_a_run_in_between_labels_nothing_new(duck: DuckDb) -> None:
    """The simulated clearance of C05 suppresses it, so the groups change before the rerun."""
    load_minic(duck)
    insert_truth(duck, [r for r in MINI_TRUTH if r[3] == "account"])
    for entity_type, entity_id, fingerprint in STATE_ROWS:
        duck.execute(
            "INSERT INTO screening_state (entity_type, entity_id, fingerprint, run_id) "
            "VALUES (?, ?, ?, 1)",
            [entity_type, entity_id, fingerprint],
        )
    settings = duck_settings(**{FRACTION: "0.3"})
    run_cases(duck, settings)
    labels = labels_mod()
    first = labels.simulate_dispositions(duck, settings)
    assert (first.labelled, first.false_positive) == (1, 1)  # the C05 group, drawn first
    before = _disposed(duck)
    assert run_cases(duck, settings).suppressed == 1

    second = labels.simulate_dispositions(duck, settings)
    assert second.labelled == 0
    assert _disposed(duck) == before


def test_b_fewer_groups_than_folds_is_a_prioritization_error() -> None:
    X, y, _ = toy_frame()
    two_groups = pd.Series([f"G{i % 2}" for i in range(len(X))], index=X.index)
    with pytest.raises(prio_error(), match="not enough labelled groups: need at least 5, got 2"):
        model_mod().fit_model(X, y, two_groups, toy_config(), seed=42)


def test_c_a_case_that_already_has_a_disposition_is_not_in_the_holdout(duck: DuckDb) -> None:
    settings = minigt(duck)
    dispose(duck, settings, CASE_C04, "FALSE_POSITIVE", reason="x", actor="analyst01")
    cases = query(duck, "SELECT case_id FROM cases WHERE run_id = 1")["case_id"]
    scores = {str(c): 0.5 for c in cases}
    h = prio_mod()._holdout(duck, settings, 1, scores)
    assert (h["n"], h["excluded_trained"]) == (len(scores) - 1, 1)


def test_d_cross_validation_never_splits_a_group(monkeypatch: pytest.MonkeyPatch) -> None:
    X, y, _ = toy_frame()
    groups = pd.Series([f"G{i // 4}" for i in range(len(X))], index=X.index)  # 10 groups of 4
    model = model_mod()
    cfg = toy_config()
    tested: list[str] = []
    for train, test in model.cv_splits(X, y, groups, cfg, 42):
        assert not set(groups.iloc[train]) & set(groups.iloc[test])
        tested += list(groups.iloc[test].unique())
    assert sorted(tested) == sorted(groups.unique())  # every group is tested exactly once

    calls: list[int] = []
    real = model.cv_splits
    monkeypatch.setattr(model, "cv_splits", lambda *a: calls.append(1) or real(*a))
    assert model.fit_model(X, y, groups, cfg, seed=42).metrics["n"] == len(X)
    assert calls == [1]


def test_e_eval_payload_names_its_population() -> None:
    from aml.cases.chain import eval_payload

    prio = prio_mod()
    t = prio.TrainingRun(1, "prio/logreg/1", "logreg", 10, 5, 5, {})
    s = prio.ScoringRun(1, 1, 1, "prio/logreg/1", 0, 0, {})
    payload = eval_payload(t, s, duck_settings())
    for part in ("cv", "holdout"):  # the top-level keys are pinned by test_prio_cli
        assert "alerted cases only" in payload[part]["population"]
        assert "Phase 7b" in payload[part]["population"]


def test_f_a_scored_case_outside_the_queue_loads_with_no_rank(duck: DuckDb) -> None:
    # a CLOSED case is scored but has no queue_rank: the NULL integer must not break load_case
    load_minic(duck)
    run = run_cases(duck, duck_settings())
    duck.execute(
        "INSERT INTO case_scores VALUES "
        f"(1, {run.run_id}, 'C-C01-20260302', 1, 'prio/logreg/1', 0.25, NULL, '[]', "
        "TIMESTAMP '2026-06-30 00:00:00')"
    )
    view = mod("aml.cases.view").load_case(duck, "C-C01-20260302")
    assert view.score == {
        "score": 0.25,
        "queue_rank": None,
        "model_version": "prio/logreg/1",
        "top_features": [],
    }
    text = mod("aml.cases.narrative").render_summary(view)
    assert "- Priority: 0.2500 (not in the queue, model prio/logreg/1)" in text.splitlines()
