"""AC7 for specs/screening-ml.md: `score` stores a score, a rank and the factors of every hit."""

from __future__ import annotations

from typing import Any

import pytest

from aml.common.db import DuckDb
from aml.screening.evaluate import truth_pairs
from aml.screening.review import latest_reviews
from aml.screening.runner import run_screening

from .helpers import AS_OF, audit_df, mod, numpy_score, query, scalar, settings_with, snapshot

FULL = {"AML__ML__SCREENING__SIMULATE_FRACTION": "1.0"}


def _pipeline() -> Any:
    return mod("aml.screening.ml.pipeline")


def _trained(db: DuckDb, **env: str) -> Any:
    s = settings_with(**{**FULL, **env})
    mod("aml.screening.ml.labels").simulate_labels(db, s)
    _pipeline().train(db, s)
    return s


def test_ac7_score_tiny(tiny_s: DuckDb) -> None:
    s = _trained(tiny_s)
    before = {
        t: snapshot(tiny_s, t, o)
        for t, o in (
            ("screening_results", "run_id, cif, entry_id"),
            ("screening_runs", "run_id"),
            ("screening_ml_labels", "label_id"),
        )
    }
    reviews = latest_reviews(tiny_s)
    base_audit = scalar(tiny_s, "SELECT COUNT(*) FROM audit_log WHERE module = 'screening'")
    run = _pipeline().score(tiny_s, s, actor="analyst01")
    assert (run.score_run_id, run.model_id, run.version) == (1, 1, "scrml/logreg/1")
    assert (run.scored, run.holdout) == (55, [])

    df = query(tiny_s, "SELECT * FROM screening_ml_scores")
    assert len(df) == 55
    assert set(df["score_run_id"]) == {1}
    assert set(df["model_version"]) == {"scrml/logreg/1"}
    assert df["score"].between(0, 1, inclusive="neither").all()
    assert ((df["score"] * 1e6).round(6) - (df["score"] * 1e6).round()).abs().max() < 1e-6
    assert sorted(df["score_rank"]) == list(range(1, 56))
    ordered = df.sort_values("score_rank")
    assert ordered["score"].is_monotonic_decreasing
    features = set(mod("aml.screening.ml.features").FEATURES)
    for top in ordered["top_features"]:
        import json

        items = json.loads(top)
        assert len(items) == 3
        assert {t["feature"] for t in items} <= features
        assert len({t["feature"] for t in items}) == 3
        mags = [abs(t["contribution"]) for t in items]
        assert mags == sorted(mags, reverse=True)
        assert all(set(t) == {"feature", "value", "contribution"} for t in items)

    artifact = scalar(tiny_s, "SELECT artifact FROM screening_ml_models WHERE model_id = 1")
    X = mod("aml.screening.ml.features").read_features(tiny_s).reset_index()
    for r in X.itertuples():
        stored = float(df[(df["cif"] == r.cif) & (df["entry_id"] == r.entry_id)]["score"].iloc[0])
        assert stored == pytest.approx(numpy_score(artifact, X.loc[r.Index]), abs=1e-6)
    truth_ranks = {
        int(df[(df["cif"] == c) & (df["entry_id"] == e)]["score_rank"].iloc[0])
        for c, e in truth_pairs(tiny_s)
    }
    assert truth_ranks == {1, 2, 3, 4, 5}

    scored = audit_df(tiny_s, "module = 'screening_ml' AND decision = 'ML_SCORED'")
    assert len(scored) == 55
    assert set(scored["entity_type"]) == {"screening_ml_score"}
    assert set(scored["version"]) == {"scrml/logreg/1"}
    assert scored["reason"].str.contains("unchanged").all()
    assert scored["reason"].str.endswith("ranking only, no clearance").all()
    by_pair = {(c, e): sc for c, e, sc in zip(df["cif"], df["entry_id"], df["score"], strict=True)}
    decisions = query(tiny_s, "SELECT cif, entry_id, decision FROM screening_current")
    system = {(c, e): d for c, e, d in decisions.itertuples(index=False)}
    for entity_id, details in zip(scored["entity_id"], scored["details"], strict=True):
        pair = tuple(entity_id.split(":"))
        assert details["score"] == pytest.approx(by_pair[pair])
        assert details["system_decision"] == system[pair]
    completed = audit_df(tiny_s, "decision = 'ML_SCORING_COMPLETED'")
    assert len(completed) == 1
    assert completed.iloc[0]["version"] == "scrml/logreg/1"

    for table, order in (
        ("screening_results", "run_id, cif, entry_id"),
        ("screening_runs", "run_id"),
        ("screening_ml_labels", "label_id"),
    ):
        assert snapshot(tiny_s, table, order) == before[table], table
    assert latest_reviews(tiny_s) == reviews
    assert scalar(tiny_s, "SELECT COUNT(*) FROM audit_log WHERE module = 'screening'") == base_audit

    second = _pipeline().score(tiny_s, s)
    assert second.score_run_id == 2
    again = query(tiny_s, "SELECT * FROM screening_ml_scores WHERE score_run_id = 2")
    key = ["cif", "entry_id"]
    merged = df.merge(again, on=key, suffixes=("", "_2"))
    assert (merged["score"] == merged["score_2"]).all()
    assert (merged["score_rank"] == merged["score_rank_2"]).all()
    assert (merged["top_features"] == merged["top_features_2"]).all()
    current = query(tiny_s, "SELECT * FROM screening_ml_scores_current")
    assert len(current) == 55
    assert set(current["score_run_id"]) == {2}

    run_screening(tiny_s, settings_with(), as_of=AS_OF)
    assert scalar(tiny_s, "SELECT COUNT(*) FROM screening_ml_scores_current") == 0


def test_ac7_unknown_model(tiny_s: DuckDb) -> None:
    s = _trained(tiny_s)
    error = mod("aml.screening.ml.model").ScreeningMlError
    with pytest.raises(error, match="unknown model_id"):
        _pipeline().score(tiny_s, s, model_id=99)
    assert scalar(tiny_s, "SELECT COUNT(*) FROM screening_ml_scores") == 0


def test_ac7_no_model(tiny_s: DuckDb) -> None:
    error = mod("aml.screening.ml.model").ScreeningMlError
    with pytest.raises(error, match="no model: run `aml screen-ml train` first"):
        _pipeline().score(tiny_s, settings_with())
    assert scalar(tiny_s, "SELECT COUNT(*) FROM screening_ml_scores") == 0


def test_ac7_holdout_is_measured_on_unlabelled_pairs(tiny_s: DuckDb) -> None:
    env = {"AML__ML__SCREENING__CV_FOLDS": "2"}
    s = settings_with(**env)
    mod("aml.screening.ml.labels").simulate_labels(tiny_s, s)
    _pipeline().train(tiny_s, s)
    run = _pipeline().score(tiny_s, s)
    assert [r["baseline"] for r in run.holdout] == ["two_tier_alert", "two_tier"]
    for r in run.holdout:
        assert (r["pairs"], r["positives"], r["rule_flagged"], r["rule_tp"]) == (16, 1, 1, 1)
        assert (r["rule_recall"], r["model_tp"]) == (1.0, 1)
        assert r["model_flagged"] >= 1
    assert scalar(tiny_s, "SELECT COUNT(*) FROM screening_ml_labels") == 39
