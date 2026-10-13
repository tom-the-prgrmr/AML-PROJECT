"""AC5 for specs/case-suppression.md: hibernation of a repeated false-positive pattern.

Fixture: MINI-S + HIB.

Hand-derived on the spec's rules: cleared pattern = (G-C04, HIGH_VELOCITY) with H1 (100M) and
H2 (120M), cleared on 2026-03-10 -> asleep until 2026-03-10 + 90 days = 2026-06-08, and an alert
leaves the sleep above 1.5 x 120M = 180 000 000 VND.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb

from .helpers import (
    N1_KEY,
    cases_current,
    duck_settings,
    enrichment,
    js,
    none_if_nan,
    query,
    run_cases,
)
from .supp_helpers import (
    CASE_C04_LATE,
    CASE_C04_S,
    H_KEYS,
    add_hib,
    audit_mark,
    audit_since,
    dispose,
    item,
    load_minis,
)

BASE_REASON = (
    "hibernated: HIGH_VELOCITY on G-C04 was a false positive 2 time(s), last cleared on "
    "2026-03-10; suppressed until 2026-06-08; amount 150,000,000 VND is not above 1.5x the "
    "largest cleared alert (120,000,000 VND)"
)


@pytest.fixture
def minis(duck: DuckDb) -> DuckDb:
    return load_minis(duck)


def _hib_run2(db: DuckDb, settings: Settings | None = None) -> Any:
    """Run 1, the C04 case cleared on 2026-03-10, the HIB alerts, run 2."""
    settings = settings or duck_settings()
    run_cases(db, settings)
    dispose(
        db,
        settings,
        CASE_C04_S,
        reason="payroll batches of a registered business",
        decided_on=date(2026, 3, 10),
    )
    add_hib(db)
    return run_cases(db, settings)


def test_ac5_run_summary(minis: DuckDb) -> None:
    run = _hib_run2(minis)
    assert run.run_id == 2
    assert (run.items, run.suppressed, run.active, run.cases) == (16, 3, 13, 6)
    assert run.suppressed_by_rule == {"GOOD_GUY": 0, "HIBERNATION": 3}
    assert run.lifted == 1


def test_ac5_h3_h4_h7_are_hibernated(minis: DuckDb) -> None:
    _hib_run2(minis)
    for name in ("H3", "H4", "H7"):
        row = item(minis, H_KEYS[name])
        assert row["status"] == "SUPPRESSED", name
        assert row["suppression_rule"] == "HIBERNATION", name
        assert none_if_nan(row["case_id"]) is None, name


def test_ac5_hibernation_reason_text(minis: DuckDb) -> None:
    _hib_run2(minis)
    assert item(minis, H_KEYS["H3"])["suppression_reason"] == BASE_REASON


def test_ac5_cleared_items_stay_in_their_case(minis: DuckDb) -> None:
    assert _hib_run2(minis).suppressed == 3
    for key in (H_KEYS["H1"], H_KEYS["H2"], N1_KEY):
        row = item(minis, key, "G-C04")
        assert (row["status"], row["case_id"]) == ("ACTIVE", CASE_C04_S), key


def test_ac5_above_ratio_alert_lifts_and_reopens_the_case(minis: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minis, settings)
    dispose(minis, settings, CASE_C04_S, reason="payroll", decided_on=date(2026, 3, 10))
    add_hib(minis)
    mark = audit_mark(minis)
    run_cases(minis, settings)
    h5 = item(minis, H_KEYS["H5"])
    assert (h5["status"], h5["retriggered"], h5["case_id"]) == ("ACTIVE", 0, CASE_C04_S)
    case = cases_current(minis)[CASE_C04_S]
    assert (case.alerts, case.status) == (4, "REOPENED")
    lifted = audit_since(minis, mark, "decision = 'SUPPRESSION_LIFTED'")
    assert len(lifted) == 1
    assert lifted.iloc[0]["reason"] == (
        "hibernation of HIGH_VELOCITY on G-C04 lifted: amount 180,000,001 VND is above 1.5x "
        "the largest cleared alert (120,000,000 VND)"
    )


def test_ac5_alert_after_the_sleep_opens_a_new_case_not_anchored_by_h7(minis: DuckDb) -> None:
    _hib_run2(minis)
    h6 = item(minis, H_KEYS["H6"])
    assert (h6["status"], h6["case_id"]) == ("ACTIVE", CASE_C04_LATE)
    assert cases_current(minis)[CASE_C04_LATE].alerts == 1
    assert "C-C04-20260608" not in cases_current(minis)


def test_ac5_h6_is_not_reported_as_lifted(minis: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minis, settings)
    dispose(minis, settings, CASE_C04_S, reason="payroll", decided_on=date(2026, 3, 10))
    add_hib(minis)
    mark = audit_mark(minis)
    run_cases(minis, settings)
    lifted = audit_since(minis, mark, "decision = 'SUPPRESSION_LIFTED'")
    assert len(lifted) == 1  # H5 only: H6 (after the sleep) was never under hibernation
    assert "180,000,001" in lifted.iloc[0]["reason"]


def test_ac5_hibernation_audit_rows(minis: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minis, settings)
    dispose(minis, settings, CASE_C04_S, reason="payroll", decided_on=date(2026, 3, 10))
    add_hib(minis)
    mark = audit_mark(minis)
    run_cases(minis, settings)
    rows = audit_since(minis, mark, "decision = 'SUPPRESSED'")
    assert len(rows) == 3
    assert set(rows["entity_type"]) == {"alert_item"}
    assert all(e.endswith("@G-C04") for e in rows["entity_id"])
    assert all(len(e) < 100 for e in rows["entity_id"])
    details = [js(d) for d in rows["details"]]  # DuckDB returns the JSON column as text
    assert {d["item_key"] for d in details} == {H_KEYS[n] for n in ("H3", "H4", "H7")}
    assert {d["rule"] for d in details} == {"HIBERNATION"}


def test_ac5_other_patterns_and_screening_are_untouched(minis: DuckDb) -> None:
    assert _hib_run2(minis).suppressed == 3
    for golden in ("G-C01", "G-C03", "G-C04"):
        assert item(minis, N1_KEY, golden)["status"] == "ACTIVE", golden
    df = query(minis, "SELECT source, suppression_rule FROM case_alerts_current")
    screening = df[df["source"] == "SCREENING"]
    assert not (screening["suppression_rule"] == "HIBERNATION").any()


def test_ac5_history_counts_the_suppressed_items(minis: DuckDb) -> None:
    _hib_run2(minis)
    assert enrichment(minis, CASE_C04_LATE)["history"]["suppressed_items"] == 3


def test_ac5_more_false_positives_required_means_no_hibernation(minis: DuckDb) -> None:
    run = _hib_run2(
        minis, duck_settings(AML__CASES__SUPPRESSION__HIBERNATION_MIN_FALSE_POSITIVES="3")
    )
    assert run.suppressed == 0
    assert run.suppressed_by_rule == {"GOOD_GUY": 0, "HIBERNATION": 0}


def test_ac5_ratio_one_suppresses_only_h7(minis: DuckDb) -> None:
    run = _hib_run2(minis, duck_settings(AML__CASES__SUPPRESSION__MATERIAL_CHANGE_RATIO="1.0"))
    assert (run.suppressed, run.lifted) == (1, 3)
    assert item(minis, H_KEYS["H7"])["status"] == "SUPPRESSED"


def test_ac5_short_sleep_ends_before_the_new_alerts(minis: DuckDb) -> None:
    # 30 days from 2026-03-10: asleep until 2026-04-09, the first new alert is on 04-10
    run = _hib_run2(minis, duck_settings(AML__CASES__SUPPRESSION__HIBERNATION_DAYS="30"))
    assert (run.suppressed, run.lifted) == (0, 0)


def test_ac5_changing_the_clearance_to_suspicious_ends_the_pattern(minis: DuckDb) -> None:
    settings = duck_settings()
    assert _hib_run2(minis, settings).suppressed == 3  # asleep until the clearance is replaced
    dispose(minis, settings, CASE_C04_S, "SUSPICIOUS", reason="second review", actor="lead01")
    run3 = run_cases(minis, settings)
    assert run3.suppressed == 0
