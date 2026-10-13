"""AC3 and AC4 for specs/case-suppression.md: the good-guy list on MINI-S."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from aml.common.db import DuckDb

from .helpers import (
    CASE_C01_B,
    CASE_C05,
    N1_KEY,
    audit_cases,
    cases_current,
    count,
    duck_settings,
    js,
    none_if_nan,
    query,
    run_cases,
)
from .supp_helpers import (
    S1_KEY,
    S2_KEY,
    SUPPRESSED_S2,
    audit_mark,
    audit_since,
    day,
    dispose,
    good_guys,
    item,
    load_minis,
)

BY_RULE_NONE = {"GOOD_GUY": 0, "HIBERNATION": 0}


@pytest.fixture
def minis(duck: DuckDb) -> DuckDb:
    return load_minis(duck)


def _run2(db: DuckDb) -> Any:
    """Run 1, FALSE_POSITIVE on the C05 case (decided 2026-06-30), run 2."""
    settings = duck_settings()
    run_cases(db, settings)
    dispose(
        db,
        settings,
        CASE_C05,
        reason="namesake, different person",
        decided_on=date(2026, 6, 30),
    )
    return run_cases(db, settings)


# ------------------------------------------------------------------ AC3
def test_ac3_first_run_suppresses_nothing(minis: DuckDb) -> None:
    run = run_cases(minis, duck_settings())
    assert (run.run_id, run.items, run.suppressed, run.cases) == (1, 11, 0, 5)
    assert run.suppressed_by_rule == BY_RULE_NONE
    assert count(minis, "good_guy_list") == 0


def test_ac3_disposition_adds_one_good_guy_row(minis: DuckDb) -> None:
    _run2(minis)
    df = good_guys(minis)
    assert len(df) == 1
    row = df.iloc[0]
    assert (row["entry_no"], row["cif"], row["entry_id"]) == (1, "C05", "WL2")
    assert (row["case_id"], row["disposition_id"]) == (CASE_C05, 1)
    assert (day(row["cleared_on"]), day(row["expires_on"])) == (
        date(2026, 6, 30),
        date(2027, 6, 30),
    )
    assert (row["customer_fingerprint"], row["entry_fingerprint"]) == ("fp-c05", "fp-wl2")
    assert row["actor"] == "analyst01"
    current = query(minis, "SELECT * FROM good_guy_current")
    assert list(current["entry_no"]) == [1]


def test_ac3_good_guy_added_audit_row(minis: DuckDb) -> None:
    _run2(minis)
    rows = audit_cases(minis, "decision = 'GOOD_GUY_ADDED'")
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["entity_type"] == "good_guy"
    assert row["entity_id"] == "C05:WL2"
    assert row["actor"] == "analyst01"
    assert row["version"] == "suppression/v1"
    assert row["reason"] == (
        "C05 x WL2 cleared as a false positive in case C-C05-20260630; suppressed until "
        "2027-06-30 unless the customer or the watchlist entry changes"
    )
    d = row["details"]
    assert (d["entry_no"], d["case_id"], d["disposition_id"]) == (1, CASE_C05, 1)
    assert (d["cleared_on"], d["expires_on"]) == ("2026-06-30", "2027-06-30")


def test_ac3_second_run_summary(minis: DuckDb) -> None:
    run = _run2(minis)
    assert run.run_id == 2
    assert (run.items, run.suppressed, run.active) == (11, 1, 10)
    assert (run.cases, run.closed, run.lifted) == (4, 0, 0)
    assert run.suppressed_by_rule == {"GOOD_GUY": 1, "HIBERNATION": 0}
    done = audit_cases(minis, "decision = 'CASE_RUN_COMPLETED'")
    last = done.iloc[-1]["details"]
    assert last["suppressed_by_rule"] == {"GOOD_GUY": 1, "HIBERNATION": 0}
    assert last["lifted"] == 0


def test_ac3_suppressed_item_row(minis: DuckDb) -> None:
    _run2(minis)
    row = item(minis, S2_KEY)
    assert row["status"] == "SUPPRESSED"
    assert row["suppression_rule"] == "GOOD_GUY"
    assert none_if_nan(row["case_id"]) is None
    assert row["retriggered"] == 0
    assert row["suppression_reason"] == SUPPRESSED_S2


def test_ac3_suppressed_case_leaves_the_queue_but_keeps_its_history(minis: DuckDb) -> None:
    _run2(minis)
    assert CASE_C05 not in cases_current(minis)
    assert count(minis, "cases", f"WHERE run_id = 1 AND case_id = '{CASE_C05}'") == 1
    assert count(minis, "case_dispositions", f"WHERE case_id = '{CASE_C05}'") == 1
    others = query(minis, f"SELECT status FROM case_alerts_current WHERE item_key <> '{S2_KEY}'")
    assert len(others) == 10
    assert set(others["status"]) == {"ACTIVE"}


def test_ac3_suppressed_audit_row(minis: DuckDb) -> None:
    _run2(minis)
    rows = audit_cases(minis, "decision = 'SUPPRESSED'")
    rows = rows[[d["run_id"] == 2 for d in rows["details"]]]
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["entity_type"] == "alert_item"
    assert row["entity_id"] == "C05:WL2@G-C05"
    assert row["version"] == "suppression/v1"
    assert row["reason"] == SUPPRESSED_S2
    assert row["details"]["item_key"] == S2_KEY
    assert row["details"]["rule"] == "GOOD_GUY"
    assert row["details"]["source"] == "SCREENING"


def test_ac3_second_clearance_and_third_run(minis: DuckDb) -> None:
    settings = duck_settings()
    _run2(minis)
    dispose(
        minis,
        settings,
        CASE_C01_B,
        reason="same name, older person",
        decided_on=date(2026, 6, 30),
    )
    run3 = run_cases(minis, settings)
    pairs = good_guys(minis)[["cif", "entry_id"]].itertuples(index=False, name=None)
    assert sorted(pairs) == [("C02", "WL1"), ("C05", "WL2")]
    assert run3.suppressed == 2
    assert run3.suppressed_by_rule == {"GOOD_GUY": 2, "HIBERNATION": 0}
    row = cases_current(minis)[CASE_C01_B]
    assert (row.alerts, row.sources, row.status) == (1, "RULE", "CLOSED")


def test_ac3_suspicious_disposition_adds_no_good_guy(minis: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minis, settings)
    dispose(minis, settings, "C-C03-20260305", "SUSPICIOUS", reason="layering")
    dispose(minis, settings, CASE_C01_B, "SUSPICIOUS", reason="a screening hit that is real")
    assert count(minis, "good_guy_list") == 0
    assert audit_cases(minis, "decision = 'GOOD_GUY_ADDED'").empty
    run2 = run_cases(minis, settings)
    assert run2.suppressed == 0
    assert item(minis, S1_KEY)["status"] == "ACTIVE"


def test_ac3_suppression_does_not_touch_the_source_tables(minis: DuckDb) -> None:
    before = (count(minis, "alerts"), count(minis, "screening_results"))
    _run2(minis)
    assert (count(minis, "alerts"), count(minis, "screening_results")) == before
    assert count(minis, "good_guy_list") == 1  # the clearance did register
    # the clear never writes a disposition of its own: the only one is the human's
    assert count(minis, "case_dispositions") == 1


# ------------------------------------------------------------------ AC4
def test_ac4_customer_data_change_lifts_and_reopens(minis: DuckDb) -> None:
    settings = duck_settings()
    _run2(minis)
    minis.execute("UPDATE screening_state SET fingerprint = 'fp-c05-v2' WHERE entity_id = 'C05'")
    mark = audit_mark(minis)
    run3 = run_cases(minis, settings)
    assert (run3.suppressed, run3.lifted, run3.reopened) == (0, 1, 1)
    row = item(minis, S2_KEY)
    assert (row["status"], row["retriggered"], row["case_id"]) == ("ACTIVE", 1, CASE_C05)
    assert cases_current(minis)[CASE_C05].status == "REOPENED"
    lifted = audit_since(minis, mark, "decision = 'SUPPRESSION_LIFTED'")
    assert len(lifted) == 1
    assert lifted.iloc[0]["entity_id"] == "C05:WL2@G-C05"
    assert lifted.iloc[0]["reason"] == (
        "customer data of C05 changed since the clearance on 2026-06-30; alert re-raised"
    )
    assert audit_since(minis, mark, "decision = 'SUPPRESSED'").empty


def test_ac4_clearing_again_writes_a_new_good_guy_row(minis: DuckDb) -> None:
    settings = duck_settings()
    _run2(minis)
    minis.execute("UPDATE screening_state SET fingerprint = 'fp-c05-v2' WHERE entity_id = 'C05'")
    run_cases(minis, settings)
    dispose(
        minis,
        settings,
        CASE_C05,
        reason="reviewed again after the KYC update",
        actor="analyst02",
        decided_on=date(2026, 7, 5),
    )
    run4 = run_cases(minis, settings)
    df = good_guys(minis)
    assert list(df["entry_no"]) == [1, 2]
    new = df.iloc[1]
    assert new["customer_fingerprint"] == "fp-c05-v2"
    assert day(new["expires_on"]) == date(2027, 7, 5)
    assert new["actor"] == "analyst02"
    assert new["disposition_id"] == 2
    assert list(query(minis, "SELECT entry_no FROM good_guy_current")["entry_no"]) == [2]
    row = item(minis, S2_KEY)
    assert row["status"] == "SUPPRESSED"
    assert "cleared on 2026-07-05 by analyst02" in row["suppression_reason"]
    assert run4.suppressed == 1
    assert run4.lifted == 0


def test_ac4_watchlist_entry_change_lifts(minis: DuckDb) -> None:
    settings = duck_settings()
    _run2(minis)
    minis.execute("UPDATE screening_state SET fingerprint = 'fp-wl2-v2' WHERE entity_id = 'WL2'")
    mark = audit_mark(minis)
    run3 = run_cases(minis, settings)
    assert (run3.suppressed, run3.lifted) == (0, 1)
    lifted = audit_since(minis, mark, "decision = 'SUPPRESSION_LIFTED'")
    assert list(lifted["reason"]) == [
        "watchlist entry WL2 changed since the clearance on 2026-06-30; alert re-raised"
    ]
    assert item(minis, S2_KEY)["retriggered"] == 1


def test_ac4_good_guy_expires_after_the_last_day(minis: DuckDb) -> None:
    settings = duck_settings()
    _run2(minis)
    on_last_day = run_cases(minis, settings, as_of=date(2027, 6, 30))
    assert on_last_day.suppressed == 1


def test_ac4_good_guy_lifts_the_day_after_expiry(minis: DuckDb) -> None:
    settings = duck_settings()
    _run2(minis)
    mark = audit_mark(minis)
    run = run_cases(minis, settings, as_of=date(2027, 7, 1))
    assert (run.suppressed, run.lifted) == (0, 1)
    lifted = audit_since(minis, mark, "decision = 'SUPPRESSION_LIFTED'")
    assert list(lifted["reason"]) == [
        "good-guy entry for C05 x WL2 expired on 2027-06-30; alert re-raised"
    ]


def test_ac4_later_suspicious_decision_ends_the_suppression(minis: DuckDb) -> None:
    settings = duck_settings()
    _run2(minis)
    dispose(
        minis,
        settings,
        CASE_C05,
        "SUSPICIOUS",
        reason="second review: true match",
        actor="lead01",
    )
    mark = audit_mark(minis)
    run3 = run_cases(minis, settings)
    assert (run3.suppressed, run3.lifted) == (0, 0)
    row = item(minis, S2_KEY)
    assert (row["status"], row["retriggered"]) == ("ACTIVE", 0)
    assert cases_current(minis)[CASE_C05].status == "CLOSED"
    assert audit_since(minis, mark, "decision IN ('SUPPRESSED', 'SUPPRESSION_LIFTED')").empty


def test_ac4_missing_fingerprint_skips_the_good_guy_row(duck: DuckDb) -> None:
    load_minis(duck, without=("WL1",))
    settings = duck_settings()
    run_cases(duck, settings)
    dispose(duck, settings, CASE_C01_B, reason="x")
    assert good_guys(duck, "WHERE cif = 'C02'").empty
    skipped = audit_cases(duck, "decision = 'GOOD_GUY_SKIPPED'")
    assert len(skipped) == 1
    assert skipped.iloc[0]["entity_id"] == "C02:WL1"
    assert "no screening fingerprint" in skipped.iloc[0]["reason"]
    run2 = run_cases(duck, settings)
    assert run2.suppressed == 0
    assert item(duck, S1_KEY)["status"] == "ACTIVE"


def test_ac4_reopen_does_not_mask_other_items(minis: DuckDb) -> None:
    # lifting one pair leaves the rest of the run as in a run without suppression
    settings = duck_settings()
    _run2(minis)
    minis.execute("UPDATE screening_state SET fingerprint = 'fp-c05-v2' WHERE entity_id = 'C05'")
    run3 = run_cases(minis, settings)
    assert (run3.items, run3.active, run3.cases, run3.lifted) == (11, 11, 5, 1)
    assert item(minis, N1_KEY, "G-C01")["status"] == "ACTIVE"
    assert js(item(minis, S1_KEY)["details"])["decision"] == "ALERT"
