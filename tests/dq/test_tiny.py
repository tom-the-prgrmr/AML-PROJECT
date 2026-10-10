"""AC6-AC8 for specs/dq-framework.md: TINY data against the Phase 1 ground truth (DuckDB)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from aml.common.config import Settings
from aml.common.db import DuckDb

from .helpers import by_rule, lower_cols, mod, parse_json_list

LABELLED_KYC = {
    "KYC_OCCUPATION_MISSING": "MISSING_OCCUPATION",
    "KYC_NATIONALITY_MISSING": "MISSING_NATIONALITY",
    "KYC_ID_FORMAT": "INVALID_ID_LENGTH",
    "KYC_DOB_FUTURE": "FUTURE_DOB",
}
EXPECTED_FAIL = {*LABELLED_KYC, "TXN_DUPLICATE", "KYC_CCCD_DOB_MISMATCH"}


def _labels(db: DuckDb, defect: str) -> frozenset[str]:
    df = db.query_df(f"SELECT entity_id FROM dq_labels WHERE defect_type = '{defect}'")
    return frozenset(str(x) for x in df.iloc[:, 0])


def test_ac6_tiny_matches_ground_truth_labels(tiny_run: tuple[DuckDb, Settings, Any]) -> None:
    db, _, run = tiny_run
    res = by_rule(run)
    for rule_id, defect in LABELLED_KYC.items():
        r = res[rule_id]
        assert (r.failed_rows, r.total_rows, r.fail_rate) == (6, 300, 0.02), rule_id
        assert r.failed_ids == _labels(db, defect), rule_id
    dup = res["TXN_DUPLICATE"]
    assert (dup.failed_rows, dup.total_rows, dup.fail_rate) == (100, 5100, 0.019608)
    assert dup.failed_ids == _labels(db, "DUPLICATE_TRANSACTION")

    agree = lower_cols(mod("aml.dq.runner").label_agreement(db, run))
    assert len(agree) == 5
    assert set(agree["rule_id"]) == {*LABELLED_KYC, "TXN_DUPLICATE"}
    assert (agree["fp"] == 0).all()
    assert (agree["fn"] == 0).all()
    assert (agree["precision"] == 1.0).all()
    assert (agree["recall"] == 1.0).all()

    mismatch = res["KYC_CCCD_DOB_MISMATCH"]
    assert mismatch.failed_rows == 5
    assert mismatch.failed_ids <= _labels(db, "FUTURE_DOB")
    for rule_id in (
        "TXN_VALUE_INVALID",
        "TXN_ACCOUNT_UNKNOWN",
        "TXN_BEFORE_ACCOUNT_OPEN",
        "TXN_FEED_STALE",
    ):
        assert res[rule_id].failed_rows == 0, rule_id
        assert res[rule_id].status == "PASS", rule_id


def test_ac7_results_and_audit_row_persisted(tiny_run: tuple[DuckDb, Settings, Any]) -> None:
    db, _, run = tiny_run
    assert run.run_id == 1
    df = lower_cols(db.query_df("SELECT * FROM dq_results WHERE run_id = 1")).set_index("rule_id")
    assert len(df) == 10
    res = by_rule(run)
    for rule_id, r in res.items():
        row = df.loc[rule_id]
        assert pd.Timestamp(row["as_of"]).date() == date(2026, 6, 30)
        assert int(row["total_rows"]) == r.total_rows
        assert int(row["failed_rows"]) == r.failed_rows
        assert row["status"] == r.status
        if r.fail_rate is None:
            assert pd.isna(row["fail_rate"])
        else:
            assert float(row["fail_rate"]) == r.fail_rate

    occ = parse_json_list(df.loc["KYC_OCCUPATION_MISSING", "sample_ids"])
    assert occ == sorted(res["KYC_OCCUPATION_MISSING"].failed_ids)
    assert len(occ) == 6
    dup = parse_json_list(df.loc["TXN_DUPLICATE", "sample_ids"])
    assert len(dup) == 20
    assert dup == sorted(res["TXN_DUPLICATE"].failed_ids)[:20]

    audit = mod("tests.dba.conftest").audit_rows(db, "module = 'dq'")
    assert len(audit) == 1
    row = audit.iloc[0]
    assert row["entity_type"] == "dq_run"
    assert row["entity_id"] == "1"
    assert row["decision"] == "DQ_RUN_COMPLETED"
    details = row["details"]
    assert details["rules"] == 10
    assert details["passed"] == 4
    assert details["failed"] == 6
    assert details["as_of"] == "2026-06-30"
    assert sorted(details["failed_rules"]) == sorted(EXPECTED_FAIL)


def test_ac8_trend_view_shows_delta_between_runs(
    duck: DuckDb, tiny_parquet: Any, dq_settings: Settings
) -> None:
    mod("aml.datagen.load").load_parquet(duck, tiny_parquet)
    runner = mod("aml.dq.runner")
    first = runner.run_dq(duck, dq_settings)
    snapshot = lower_cols(
        duck.query_df(
            "SELECT run_id, rule_id, total_rows, failed_rows, fail_rate, status, sample_ids "
            "FROM dq_results WHERE run_id = 1 ORDER BY rule_id"
        )
    )
    missing = sorted(first.results[0].failed_ids)
    assert first.results[0].rule_id == "KYC_OCCUPATION_MISSING"
    for cif in missing[:2]:
        duck.execute(f"UPDATE customers SET occupation = 'Teacher' WHERE cif = '{cif}'")

    second = runner.run_dq(duck, dq_settings)
    assert second.run_id == 2

    trend = lower_cols(duck.query_df("SELECT * FROM dq_trend"))
    assert len(trend) == 20

    def row(rule: str, run_id: int) -> pd.Series:
        sel = trend[(trend["rule_id"] == rule) & (trend["run_id"] == run_id)]
        assert len(sel) == 1
        return sel.iloc[0]

    r1 = row("KYC_OCCUPATION_MISSING", 1)
    assert int(r1["failed_rows"]) == 6
    assert pd.isna(r1["prev_failed_rows"])
    assert pd.isna(r1["delta_failed_rows"])
    r2 = row("KYC_OCCUPATION_MISSING", 2)
    assert int(r2["failed_rows"]) == 4
    assert int(r2["prev_failed_rows"]) == 6
    assert int(r2["delta_failed_rows"]) == -2
    d2 = row("TXN_DUPLICATE", 2)
    assert int(d2["failed_rows"]) == 100
    assert int(d2["delta_failed_rows"]) == 0

    after = lower_cols(
        duck.query_df(
            "SELECT run_id, rule_id, total_rows, failed_rows, fail_rate, status, sample_ids "
            "FROM dq_results WHERE run_id = 1 ORDER BY rule_id"
        )
    )
    pd.testing.assert_frame_equal(snapshot, after)
    assert len(after) == 10
