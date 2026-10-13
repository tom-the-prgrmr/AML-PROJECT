"""Regression tests for the review of Phase 7b-supp: re-clearing a case, ratio boundary."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from aml.common.config import load_settings
from aml.common.db import DuckDb

from .helpers import CASE_C01_B, audit_cases, duck_settings, run_cases
from .supp_helpers import (
    S1_KEY,
    audit_mark,
    audit_since,
    day,
    dispose,
    good_guys,
    item,
    load_minis,
    supp,
)


@pytest.fixture
def minis(duck: DuckDb) -> DuckDb:
    return load_minis(duck)


def _cleared_twice(db: DuckDb, second: str = "FALSE_POSITIVE") -> None:
    """Run 1, clear C01_B, run 2 (C02 x WL1 suppressed), then a second decision on the case."""
    settings = duck_settings()
    run_cases(db, settings)
    dispose(db, settings, CASE_C01_B, decided_on=date(2026, 6, 30))
    run_cases(db, settings)
    dispose(
        db,
        settings,
        CASE_C01_B,
        second,
        reason="reopened by a new rule alert, cleared again",
        actor="analyst02",
        decided_on=date(2026, 7, 5),
    )


def test_clearing_again_renews_a_suppressed_pair(minis: DuckDb) -> None:
    _cleared_twice(minis)
    mark = audit_mark(minis)
    run3 = run_cases(minis, duck_settings())
    df = good_guys(minis)
    assert list(df["entry_no"]) == [1, 2]
    assert list(df["disposition_id"]) == [1, 2]
    assert day(df.iloc[1]["expires_on"]) == date(2027, 7, 5)
    assert (run3.suppressed, run3.lifted) == (1, 0)
    assert item(minis, S1_KEY)["status"] == "SUPPRESSED"
    assert audit_since(minis, mark, "decision = 'SUPPRESSION_LIFTED'").empty
    added = audit_cases(minis, "decision = 'GOOD_GUY_ADDED'")
    assert len(added) == 2
    assert added.iloc[1]["details"]["entry_no"] == 2


def test_clearing_again_after_a_fingerprint_change_does_not_renew(minis: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minis, settings)
    dispose(minis, settings, CASE_C01_B, decided_on=date(2026, 6, 30))
    run_cases(minis, settings)
    minis.execute("UPDATE screening_state SET fingerprint = 'fp-c02-v2' WHERE entity_id = 'C02'")
    dispose(minis, settings, CASE_C01_B, decided_on=date(2026, 7, 5), actor="analyst02")
    df = good_guys(minis)
    assert list(df["entry_no"]) == [1, 2]  # carried with the old fingerprint, not renewed
    assert day(df.iloc[1]["expires_on"]) == date(2027, 6, 30)
    assert df.iloc[1]["customer_fingerprint"] == "fp-c02"
    mark = audit_mark(minis)
    run3 = run_cases(minis, settings)
    row = item(minis, S1_KEY)
    assert (row["status"], row["retriggered"]) == ("ACTIVE", 1)
    assert (run3.suppressed, run3.lifted) == (0, 1)
    assert len(audit_since(minis, mark, "decision = 'SUPPRESSION_LIFTED'")) == 1


def test_clearing_again_as_suspicious_ends_the_suppression(minis: DuckDb) -> None:
    _cleared_twice(minis, "SUSPICIOUS")
    mark = audit_mark(minis)
    run3 = run_cases(minis, duck_settings())
    assert list(good_guys(minis)["entry_no"]) == [1]
    assert (run3.suppressed, run3.lifted) == (0, 0)
    assert item(minis, S1_KEY)["status"] == "ACTIVE"
    assert audit_since(minis, mark, "decision IN ('SUPPRESSED', 'SUPPRESSION_LIFTED')").empty


def test_hibernation_boundary_with_a_float_ratio() -> None:
    cfg = load_settings(environ={}).cases.suppression.model_copy(
        update={"material_change_ratio": 1.15}
    )
    pattern = supp().HibernationPattern(
        golden_customer_id="G-C04",
        rule_id="HIGH_VELOCITY",
        false_positives=2,
        cleared_on=date(2026, 3, 10),
        max_amount_vnd=3_000_000,
        handled=frozenset({"k1"}),
    )
    when = datetime(2026, 4, 10, 9)

    def verdict(amount: int) -> tuple[bool, bool]:
        v = supp().hibernation_verdict(
            pattern, item_key="k9", event_ts=when, amount_vnd=amount, cfg=cfg
        )
        return v.suppress, v.lifted

    assert verdict(3_450_000) == (True, False)
    assert verdict(3_450_001) == (False, True)
