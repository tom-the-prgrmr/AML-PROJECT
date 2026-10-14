"""AC6 for specs/memo-analysis.md: memo columns join the 7c model only once labels exist; a risk
column never lowers a score (`fit_guarded`); scoring never fails for a missing label."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from aml.common.db import Database, DuckDb
from tests.cases.helpers import count, duck_settings, enrichment, js, query, run_cases
from tests.cases.prio_helpers import (
    TINY_TOP,
    all_features,
    audit_rows,
    make_tiny_l,
    numpy_scores,
    prio_mod,
    table_digest,
    text,
    toy_config,
    toy_frame,
)
from tests.cases.prio_helpers import features_mod as cases_features

from .helpers import MODEL, Stub, classify, features_mod, risk_script


def _model(db: Database, model_id: int) -> Any:
    return query(db, f"SELECT * FROM case_models WHERE model_id = {model_id}").iloc[0]


def _decisions(db: Database) -> dict[str, Any]:
    return {
        "case_dispositions": table_digest(db, "case_dispositions", "disposition_id"),
        "good_guy_list": table_digest(db, "good_guy_list", "entry_no"),
    }


def _trained(db: Database, version: str) -> dict[str, Any]:
    rows = audit_rows(db, f"decision = 'MODEL_TRAINED' AND entity_id = '{version}'")
    assert len(rows) == 1
    return dict(rows["details"][0])


def _scoring(db: Database, score_run_id: int) -> dict[str, Any]:
    rows = audit_rows(db, f"decision = 'SCORING_RUN_COMPLETED' AND entity_id = '{score_run_id}'")
    assert len(rows) == 1
    return dict(rows["details"][0])


def _a_txn_in_the_window(db: Database, case_id: str) -> str:
    blocks = enrichment(db, case_id)
    cifs = ", ".join(f"'{c}'" for c in blocks["linked_cifs"]["cifs"])
    start, end = blocks["txn_summary"]["window_start"], blocks["txn_summary"]["window_end"]
    df = query(
        db,
        f"SELECT MIN(txn_id) AS txn_id FROM txn_legs WHERE cif IN ({cifs}) "
        f"AND txn_ts >= DATE '{start}' AND txn_ts < DATE '{end}' + INTERVAL 1 DAY",
    )
    assert df["txn_id"][0] is not None
    return str(df["txn_id"][0])


def test_ac6_train_and_score_with_and_without_memo_labels(tiny_cases: DuckDb) -> None:
    db = tiny_cases
    settings = duck_settings()
    prio, f = prio_mod(), features_mod()
    features = list(all_features())
    make_tiny_l(db, settings)  # 38 decisions on run 1 (27 / 11); the current run is 2
    decisions = _decisions(db)

    # before any classification: exactly the 7c behaviour, no Ollama needed
    t1 = prio.train(db, settings)
    assert t1.version == "prio/logreg/1"
    m1 = _model(db, 1)
    assert m1["feature_version"] == "features/v1"
    assert js(m1["features"]) == features
    assert "memo" not in js(m1["params"])
    assert "memo" not in _trained(db, t1.version)
    assert count(db, "case_memo_features") == 0

    classify(db, settings, Stub(risk_script()))
    t2 = prio.train(db, settings)
    assert (t2.version, t2.cases) == ("prio/logreg/2", 38)
    m2 = _model(db, 2)
    assert m2["feature_version"] == "features/v1+memo/v1"
    names = js(m2["features"])
    assert names[:35] == features
    extra = names[35:]
    assert "memo_txns" in extra
    assert extra == [name for name in f.MEMO_FEATURES if name in extra]  # ordered subsequence
    memo = js(m2["params"])["memo"]
    assert (memo["version"], memo["model"], memo["labels_rev"]) == ("memo/v1", MODEL, 0)
    assert memo["by_method"] == {"RULE": 6, "LLM": 35, "HUMAN": 0, "FALLBACK": 0}
    assert set(names) | set(memo["dropped_features"]) >= set(f.MEMO_FEATURES)
    artifact = json.loads(text(m2["artifact"]))
    coef = dict(zip(artifact["features"], artifact["coef"], strict=True))
    assert all(coef[name] >= 0 for name in f.NON_NEGATIVE if name in names)
    assert _trained(db, t2.version)["memo"] == memo
    assert count(db, "case_memo_features") == 312  # 52 cases x 6, the snapshot of the decisions
    assert count(db, "case_memo_features", "WHERE run_id = 1") == 312

    s = prio.score(db, settings)
    assert (s.cases, s.queue, s.model_id) == (52, 14, 2)
    assert count(db, "case_memo_features", "WHERE run_id = 2") == 312
    assert count(db, "case_memo_features") == 624
    X = cases_features().read_features(db, 2).join(f.read_memo_features(db, settings, 2))
    expected = numpy_scores(text(m2["artifact"]), X)
    stored = query(
        db, f"SELECT case_id, score FROM case_scores WHERE score_run_id = {s.score_run_id}"
    ).set_index("case_id")["score"]
    assert len(stored) == 52
    assert float((stored - expected.loc[stored.index]).abs().max()) <= 1e-6
    assert _scoring(db, s.score_run_id)["memo_features"] == "stored"

    s1 = prio.score(db, settings, model_id=1)  # the 35-column model still scores
    assert s1.cases == 52
    assert "memo_features" not in _scoring(db, s1.score_run_id)

    t3 = prio.train(db, duck_settings(AML__MEMO__FEATURES="off"))
    m3 = _model(db, t3.model_id)
    assert js(m3["features"]) == features and m3["feature_version"] == "features/v1"
    assert "memo" not in js(m3["params"])

    txn_id = _a_txn_in_the_window(db, TINY_TOP)
    db.execute(
        f"UPDATE transactions SET memo = 'memo moi chua phan loai' WHERE txn_id = '{txn_id}'"
    )
    assert run_cases(db, settings).run_id == 3
    s3 = prio.score(db, settings, model_id=2)  # a missing label never blocks the queue
    assert s3.cases == 52
    assert _scoring(db, s3.score_run_id)["memo_features"] == "zeros"
    assert count(db, "case_memo_features", "WHERE run_id = 3") == 0

    assert _decisions(db) == decisions


def _toy_m(flag_when: int | None) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """TOY-M: TOY plus six memo columns of 0.0; `memo_suspicious_wording` = 1 when i % 4 == flag."""
    X, y, groups = toy_frame()
    for name in features_mod().MEMO_FEATURES:
        X[name] = 0.0
    if flag_when is not None:
        X["memo_suspicious_wording"] = [1.0 if i % 4 == flag_when else 0.0 for i in range(40)]
    return X, y, groups


def _coef(model: Any) -> dict[str, float]:
    a = json.loads(model.artifact)
    return dict(
        zip(a["features"], np.asarray(a["coef"], dtype=float).ravel().tolist(), strict=True)
    )


def test_ac6_fit_guarded_drops_a_risk_column_with_a_negative_coefficient() -> None:
    f = features_mod()
    X, y, groups = _toy_m(1)  # TOY-M-NEG: the flag only appears on FALSE_POSITIVE rows
    model, dropped = f.fit_guarded(X, y, groups, toy_config(), seed=42)
    assert dropped == ("memo_suspicious_wording",)
    assert len(model.features) == 40 and "memo_suspicious_wording" not in model.features
    assert model.metrics["roc_auc"] == 1.0


def test_ac6_fit_guarded_keeps_a_risk_column_with_a_positive_coefficient() -> None:
    f = features_mod()
    X, y, groups = _toy_m(0)  # TOY-M-POS: the flag only appears on SUSPICIOUS rows
    model, dropped = f.fit_guarded(X, y, groups, toy_config(), seed=42)
    assert dropped == ()
    assert len(model.features) == 41
    coef = _coef(model)
    assert coef["memo_suspicious_wording"] > 0
    assert coef["memo_gambling_like"] == 0.0  # an all-zero column
    again, _ = f.fit_guarded(X, y, groups, toy_config(), seed=42)
    assert (again.artifact, again.data_hash) == (model.artifact, model.data_hash)


def test_ac6_fit_guarded_lightgbm_drops_the_three_risk_columns() -> None:
    pytest.importorskip("lightgbm")
    f = features_mod()
    X, y, groups = _toy_m(0)
    model, dropped = f.fit_guarded(X, y, groups, toy_config(), seed=42, kind="lightgbm")
    assert dropped == f.NON_NEGATIVE
    assert len(model.features) == 38


def test_ac6_review_train_and_score_on_a_schema_without_ddl_190(tiny_cases: DuckDb) -> None:
    """AC6 (review fix): with `features: auto` but no memo tables (a database built before DDL
    190), training and scoring take the Phase 7c path and the audit row says why."""
    db = tiny_cases
    settings = duck_settings()
    make_tiny_l(db, settings)
    for view in ("memo_labels_current", "memo_overrides_current", "memo_classifications_current"):
        db.execute(f"DROP VIEW {view}")
    for table in ("case_memo_features", "memo_overrides", "memo_classifications", "memo_runs"):
        db.execute(f"DROP TABLE {table}")

    t = prio_mod().train(db, settings)
    m = _model(db, t.model_id)
    assert js(m["features"]) == list(all_features()) and m["feature_version"] == "features/v1"
    details = _trained(db, t.version)
    assert "memo" not in details
    assert "aml init-db" in details["memo_skipped"]
    s = prio_mod().score(db, settings)
    assert s.cases == 52
    assert "memo_features" not in _scoring(db, s.score_run_id)
