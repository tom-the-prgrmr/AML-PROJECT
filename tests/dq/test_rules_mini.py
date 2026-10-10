"""AC3-AC5 for specs/dq-framework.md on the hand-built MINI data set (DuckDB)."""

from __future__ import annotations

from datetime import date
from typing import Any

from aml.common.config import Settings
from aml.common.db import DuckDb

from .helpers import ALL_RULES, by_rule, insert_txn, load_mini, mod

AS_OF = date(2026, 6, 30)


def _run(db: DuckDb, settings: Settings) -> dict[str, Any]:
    return by_rule(mod("aml.dq.runner").run_dq(db, settings, as_of=AS_OF))


def test_ac3_kyc_rules_flag_exact_customers(duck: DuckDb, dq_settings: Settings) -> None:
    load_mini(duck)
    res = _run(duck, dq_settings)
    assert res["KYC_OCCUPATION_MISSING"].failed_ids == frozenset({"C2"})
    assert res["KYC_NATIONALITY_MISSING"].failed_ids == frozenset({"C2"})
    assert res["KYC_ID_FORMAT"].failed_ids == frozenset({"C2", "C5"})
    assert res["KYC_DOB_FUTURE"].failed_ids == frozenset({"C2"})
    assert res["KYC_CCCD_DOB_MISMATCH"].failed_ids == frozenset({"C4", "C6"})
    for rule_id in ALL_RULES[:5]:
        assert res[rule_id].total_rows == 6, rule_id
    assert res["KYC_ID_FORMAT"].fail_rate == 0.333333
    assert res["KYC_ID_FORMAT"].status == "FAIL"


def test_ac4_transaction_rules_flag_exact_transactions(duck: DuckDb, dq_settings: Settings) -> None:
    load_mini(duck)
    res = _run(duck, dq_settings)
    assert res["TXN_DUPLICATE"].failed_ids == frozenset({"T2", "T3", "T9"})
    assert res["TXN_VALUE_INVALID"].failed_ids == frozenset({"T7"})
    assert res["TXN_ACCOUNT_UNKNOWN"].failed_ids == frozenset({"T6"})
    assert res["TXN_BEFORE_ACCOUNT_OPEN"].failed_ids == frozenset({"T4"})
    for rule_id in ALL_RULES[5:9]:
        assert res[rule_id].total_rows == 9, rule_id
    assert res["TXN_DUPLICATE"].fail_rate == 0.333333
    stale = res["TXN_FEED_STALE"]
    assert (stale.total_rows, stale.failed_rows, stale.status) == (1, 0, "PASS")


def test_ac5_feed_stale_boundary_and_no_data(duck: DuckDb, dq_settings: Settings) -> None:
    mod("aml.dba.schema").apply_schema(duck)
    assert dq_settings.dq.max_feed_lag_days == 1
    assert dq_settings.dq.sample_size == 20

    insert_txn(duck, "S1", "'EXT-1'", "'EXT-2'", "2026-06-28 23:59:59", 1000, "CASH")
    stale = _run(duck, dq_settings)["TXN_FEED_STALE"]
    assert (stale.failed_rows, stale.total_rows, stale.fail_rate) == (1, 1, 1.0)
    assert stale.status == "FAIL"
    assert stale.failed_ids == frozenset({"transactions"})

    duck.execute("UPDATE transactions SET txn_ts = TIMESTAMP '2026-06-29 00:00:00'")
    stale = _run(duck, dq_settings)["TXN_FEED_STALE"]
    assert (stale.status, stale.failed_rows) == ("PASS", 0)

    duck.execute("DELETE FROM transactions WHERE txn_id = 'S1'")
    res = _run(duck, dq_settings)
    assert set(res) == set(ALL_RULES)
    for rule_id, r in res.items():
        assert r.status == "NO_DATA", rule_id
        assert (r.total_rows, r.failed_rows) == (0, 0), rule_id
        assert r.fail_rate is None, rule_id
