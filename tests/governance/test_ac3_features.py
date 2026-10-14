"""AC3 for specs/ml-governance.md: the 35 features of a below-the-line customer."""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from aml.common.db import Database
from tests.cases.prio_helpers import EXPECTED_FEATURES
from tests.memo.helpers import MODEL

from .helpers import btl, build_tiny_b, count, mod, query, stub_risk

AS_OF = date(2026, 6, 30)
KYC = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
ALERT_FEATURES = EXPECTED_FEATURES[:19]
MEMO_COLUMNS = (
    "memo_txns",
    "memo_salary",
    "memo_loan_repayment",
    "memo_gambling_like",
    "memo_crypto_like",
    "memo_suspicious_wording",
)


def _cifs(db: Database, golden_id: str) -> list[str]:
    df = query(db, f"SELECT cif FROM customer_golden WHERE golden_customer_id = '{golden_id}'")
    return sorted(df["cif"]) or [golden_id.removeprefix("G-")]


@pytest.fixture(scope="module")
def state(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[SimpleNamespace]:
    db, settings = build_tiny_b(tiny_stages, tmp_path_factory)
    sample = btl().draw_sample(db, settings)
    before = (count(db, "case_features"), count(db, "case_enrichment"))
    first = btl().write_btl_features(db, settings, sample.sample_id)
    rows = count(db, "btl_features", f"WHERE sample_id = {sample.sample_id}")
    second = btl().write_btl_features(db, settings, sample.sample_id)
    frame = btl().read_btl_features(db, settings, sample.sample_id)
    yield SimpleNamespace(
        db=db, settings=settings, sample=sample, first=first, second=second, rows=rows,
        total=count(db, "btl_features"), frame=frame, before=before,
        after=(count(db, "case_features"), count(db, "case_enrichment")),
    )  # fmt: skip
    db.close()


def test_ac3_rows_written_once(state: SimpleNamespace) -> None:
    assert (state.first, state.second) == (1750, 0)
    assert state.rows == 1750 and state.total == 1750


def test_ac3_frame_shape_and_values(state: SimpleNamespace) -> None:
    f = state.frame
    ids = [m.golden_customer_id for m in state.sample.members]
    assert f.shape == (50, 35)
    assert list(f.index) == ids == sorted(ids)
    assert list(f.columns) == list(EXPECTED_FEATURES)
    assert all(math.isfinite(v) for v in f.to_numpy(dtype=float).ravel())
    assert (f[list(ALERT_FEATURES)] == 0.0).all().all()
    assert (f["prior_cases"] == 0.0).all()


def test_ac3_values_follow_the_enrichment_of_a_case(state: SimpleNamespace) -> None:
    activity = mod("aml.cases.enrich_txn").txn_activity
    db, f = state.db, state.frame
    for golden_id in f.index:
        cifs = _cifs(db, golden_id)
        summary = activity(db, cifs, golden_id, AS_OF, days=90, top_n=5).summary
        assert f.at[golden_id, "txn_count"] == summary["txn_count"], golden_id
        risks = query(
            db, "SELECT kyc_risk FROM customers WHERE cif IN ('" + "', '".join(cifs) + "')"
        )["kyc_risk"]
        assert f.at[golden_id, "kyc_risk_level"] == max(KYC[r] for r in risks), golden_id
        assert f.at[golden_id, "cifs"] == len(cifs)


def test_ac3_no_case_table_changes(state: SimpleNamespace) -> None:
    assert state.before == state.after


def test_ac3_the_ground_truth_is_not_read_for_features(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    db, settings = build_tiny_b(tiny_stages, tmp_path_factory)
    try:
        sample = btl().draw_sample(db, settings)
        db.execute("DROP TABLE ground_truth")
        assert btl().write_btl_features(db, settings, sample.sample_id) == 1750
    finally:
        db.close()


def test_ac3_memo_columns_follow_the_labels(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    db, settings = build_tiny_b(tiny_stages, tmp_path_factory)
    try:
        sample = btl().draw_sample(db, settings)
        btl().write_btl_features(db, settings, sample.sample_id)
        assert btl().read_btl_features(db, settings, sample.sample_id, memo=True) is None
        mod("aml.memo.runner").classify_memos(db, settings, stub_risk())
        got = btl().read_btl_features(db, settings, sample.sample_id, memo=True)
        assert got.shape == (50, 41)
        assert list(got.columns[-6:]) == list(MEMO_COLUMNS)
        memo = mod("aml.memo.features")
        labels_df = mod("aml.memo.store").read_labels(db, settings)
        labels = {
            k: (c, m)
            for k, c, m in zip(
                labels_df["memo_key"], labels_df["category"], labels_df["method"], strict=True
            )
        }
        assert settings.ollama.llm_model == MODEL
        for golden_id in got.index:
            cifs = "', '".join(_cifs(db, golden_id))
            memos = query(
                db,
                "SELECT DISTINCT t.txn_id, t.memo FROM transactions t "
                "JOIN accounts a ON a.account_id IN (t.from_account_id, t.to_account_id) "
                f"WHERE a.cif IN ('{cifs}') AND t.txn_ts >= TIMESTAMP '2026-04-02 00:00:00' "
                "AND t.txn_ts < TIMESTAMP '2026-07-01 00:00:00'",
            )["memo"]
            want = memo.count_memos(list(memos), labels, settings.memo.max_chars)
            assert want is not None
            assert got.loc[golden_id, list(MEMO_COLUMNS)].tolist() == [
                want[c] for c in MEMO_COLUMNS
            ]
    finally:
        db.close()
