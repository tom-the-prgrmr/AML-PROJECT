"""AC5 for specs/memo-analysis.md: memo features per case, all-or-nothing, 7c tables unchanged."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from aml.common.db import DuckDb
from tests.cases.helpers import (
    CASE_C01_A,
    CASE_C01_B,
    CASE_C05,
    count,
    duck_settings,
    mod,
    query,
    run_cases,
)

from .helpers import K_LOAN, MODEL, SCRIPT, VERSION, Stub, classify, features_mod, memo_error, memoc


def _row(frame: pd.DataFrame, case_id: str) -> dict[str, float]:
    return {k: float(v) for k, v in frame.loc[case_id].items()}


def _values(*numbers: int) -> dict[str, float]:
    return dict(zip(features_mod().MEMO_FEATURES, [float(n) for n in numbers], strict=True))


def test_ac5_memo_features_are_written_once_all_or_nothing(duck: DuckDb) -> None:
    settings = memoc(duck)
    f = features_mod()
    assert run_cases(duck, settings).cases == 5

    assert f.write_memo_features(duck, settings, 1) == 0
    assert f.read_memo_features(duck, settings, 1) is None
    assert count(duck, "case_memo_features") == 0

    with pytest.raises(memo_error()):
        classify(duck, settings, None)  # only the RULE label exists now
    assert f.write_memo_features(duck, settings, 1) == 0
    assert f.read_memo_features(duck, settings, 1) is None
    assert count(duck, "case_memo_features") == 0

    classify(duck, settings, Stub(SCRIPT))
    assert f.write_memo_features(duck, settings, 1) == 30
    assert f.write_memo_features(duck, settings, 1) == 0
    stored = query(duck, "SELECT * FROM case_memo_features")
    assert len(stored) == 30
    assert set(stored["memo_version"]) == {VERSION}
    assert set(stored["llm_model"]) == {MODEL}
    assert {int(v) for v in stored["labels_rev"]} == {0}

    frame = f.read_memo_features(duck, settings, 1)
    assert frame.shape == (5, 6)
    assert list(frame.index) == sorted(frame.index)
    assert tuple(frame.columns) == f.MEMO_FEATURES
    assert all(isinstance(v, float) and math.isfinite(v) for v in frame.to_numpy().ravel().tolist())
    # memo_txns, salary, loan_repayment, gambling_like, crypto_like, suspicious_wording
    assert _row(frame, CASE_C01_A) == _values(4, 1, 1, 0, 1, 1)  # T01, T02, T04, T05, T06
    assert _row(frame, CASE_C01_B) == _values(3, 0, 0, 1, 1, 1)  # T05, T06, T07
    assert _row(frame, CASE_C05) == _values(0, 0, 0, 0, 0, 0)  # no transactions

    cases = mod("aml.cases.features")
    assert cases.write_features(duck, 1) == 175  # 7c is unchanged
    assert count(duck, "case_features") == 175
    assert count(duck, "case_features", "WHERE feature LIKE 'memo\\_%' ESCAPE '\\'") == 0
    assert cases.read_features(duck, 1).shape == (5, 35)

    duck.execute("UPDATE transactions SET memo = 'memo moi chua phan loai' WHERE txn_id = 'T06'")
    run_cases(duck, settings)  # run 2 sees a memo without a label
    assert f.write_memo_features(duck, settings, 2) == 0
    assert f.read_memo_features(duck, settings, 2) is None
    pd.testing.assert_frame_equal(f.read_memo_features(duck, settings, 1), frame)

    other = duck_settings(AML__OLLAMA__LLM_MODEL="other-model")
    assert f.read_memo_features(duck, other, 1) is None  # labels of another model are not mixed in


def test_ac5_suspicious_wording_from_the_model_is_not_counted(duck: DuckDb) -> None:
    settings = memoc(duck)
    f = features_mod()
    run_cases(duck, settings)
    classify(duck, settings, Stub(SCRIPT | {K_LOAN: "suspicious_wording"}))
    assert f.write_memo_features(duck, settings, 1) == 30
    row = _row(f.read_memo_features(duck, settings, 1), CASE_C01_A)
    assert row["memo_suspicious_wording"] == 1.0  # T05 (RULE) only; T02 (LLM) is not counted
    assert row["memo_loan_repayment"] == 0.0
    assert row["memo_txns"] == 4.0
