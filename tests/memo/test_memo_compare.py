"""AC7 for specs/memo-analysis.md: the honest comparison with and without memo features."""

from __future__ import annotations

import pandas as pd
import pytest

from aml.common.db import DuckDb
from tests.cases.helpers import count, duck_settings, mod
from tests.cases.prio_helpers import all_features, make_tiny_l, prio_mod, toy_config

from .helpers import MODEL, Stub, classify, features_mod, memo_audit, memo_error, risk_script

KEYS = {"memo", "data", "base", "with_memo", "delta", "population"}


def _toy_g() -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """TOY-G: 40 rows, every 7c feature constant, so the base model cannot rank at all."""
    ids = [f"C-T{i:02d}-20260101" for i in range(40)]
    X = pd.DataFrame(0.0, index=pd.Index(ids, name="case_id"), columns=list(all_features()))
    X["alerts"] = 1.0
    y = pd.Series([1 if i % 2 == 0 else 0 for i in range(40)], index=X.index)
    return X, y, pd.Series(list(X.index), index=X.index)


def _with_memo(X: pd.DataFrame, gambling: pd.Series | None) -> pd.DataFrame:
    out = X.copy()
    for name in features_mod().MEMO_FEATURES:
        out[name] = 0.0
    if gambling is not None:
        out["memo_gambling_like"] = gambling.astype(float)
    return out


def test_ac7_compare_feature_sets_on_toy_g() -> None:
    f = features_mod()
    X, y, groups = _toy_g()
    c = f.compare_feature_sets(X, _with_memo(X, y), y, groups, toy_config(), seed=42)
    assert c["base"]["cv"]["roc_auc"] == 0.5
    assert c["with_memo"]["cv"]["roc_auc"] == 1.0
    assert c["delta"]["cv_roc_auc"] == 0.5
    assert c["delta"]["cv_pr_auc"] == 0.5
    assert c["base"]["features"] == 35
    assert c["with_memo"]["features"] == 41
    assert c["with_memo"]["dropped_features"] == []

    flat = f.compare_feature_sets(X, _with_memo(X, None), y, groups, toy_config(), seed=42)
    assert flat["delta"]["cv_roc_auc"] == 0.0
    assert flat["delta"]["cv_pr_auc"] == 0.0


def test_ac7_compare_memo_features_on_tiny_l(tiny_cases: DuckDb) -> None:
    db = tiny_cases
    settings = duck_settings()
    compare = mod("aml.memo.compare").compare_memo_features
    f = features_mod()
    make_tiny_l(db, settings)

    with pytest.raises(memo_error()) as caught:
        compare(db, settings)  # nothing classified yet
    assert "memo features are not available: run `aml memo classify` first" in str(caught.value)
    assert len(memo_audit(db)) == 0

    classify(db, settings, Stub(risk_script()))
    tables = ("case_models", "case_scores", "case_dispositions")
    before = [count(db, t) for t in tables]
    audited = len(memo_audit(db, "decision = 'MEMO_FEATURES_COMPARED'"))

    p = compare(db, settings)
    assert set(p) == KEYS
    assert p["memo"] == {
        "version": "memo/v1",
        "model": MODEL,
        "keys": 41,
        "labels_rev": 0,
        "by_method": {"RULE": 6, "LLM": 35, "HUMAN": 0, "FALLBACK": 0},
        "by_category": {
            "salary": 0,
            "loan_repayment": 0,
            "gambling_like": 5,
            "crypto_like": 3,
            "suspicious_wording": 6,
            "other": 27,
        },
    }
    data = p["data"]
    assert (data["cases"], data["suspicious"], data["false_positive"]) == (38, 27, 11)
    assert 0 <= data["cases_with_memo"] <= 38
    nonzero = data["nonzero"]
    assert tuple(nonzero) == f.MEMO_FEATURES
    assert nonzero["memo_salary"] == 0 and nonzero["memo_loan_repayment"] == 0
    assert nonzero["memo_gambling_like"] + nonzero["memo_crypto_like"] >= 1
    assert p["base"]["features"] == 35
    assert p["with_memo"]["cv"]["n"] == 38
    for name in ("roc_auc", "pr_auc"):
        gap = round(p["with_memo"]["cv"][name] - p["base"]["cv"][name], 4)
        assert p["delta"][f"cv_{name}"] == gap
    assert p["delta"]["holdout_roc_auc"] is None  # the 14 open cases of TINY-L have one class
    assert [count(db, t) for t in tables] == before  # nothing stored

    again = compare(db, settings)
    for key in ("base", "with_memo", "delta"):
        assert again[key] == p[key]
    assert [count(db, t) for t in tables] == before

    rows = memo_audit(db, "decision = 'MEMO_FEATURES_COMPARED'")
    assert len(rows) == audited + 2  # one per call
    for row in rows.itertuples():
        assert row.entity_type == "model_comparison"
        assert row.reason.startswith(
            "compared the ranking model with and without memo features on 38 labelled cases"
        )
        assert row.reason.endswith("measurement only, no model stored")

    base = prio_mod().train(db, duck_settings(AML__MEMO__FEATURES="off"))
    assert p["base"]["cv"] == base.metrics
    assert (base.metrics["n"], base.metrics["prevalence"]) == (38, 0.7105)
