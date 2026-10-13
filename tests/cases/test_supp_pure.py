"""AC1, AC2 and AC6 for specs/case-suppression.md: config, DDL 170, and the two pure verdicts."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from aml.common.config import load_settings
from aml.common.db import SQL_ROOT, DuckDb, sql_file
from aml.dba.schema import SCHEMA_SCRIPTS, apply_schema

from .helpers import count
from .supp_helpers import supp

DDL = "ddl/170_case_suppression.sql"


# ------------------------------------------------------------------ AC1
def test_ac1_default_suppression_config() -> None:
    c = load_settings(environ={}).cases.suppression
    assert c.good_guy_days == 365
    assert c.hibernation_days == 90
    assert c.hibernation_min_false_positives == 2
    assert c.material_change_ratio == 1.5


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"AML__CASES__SUPPRESSION__GOOD_GUY_DAYS": "0"}, "good_guy_days must be >= 1"),
        (
            {"AML__CASES__SUPPRESSION__MATERIAL_CHANGE_RATIO": "0.9"},
            "material_change_ratio must be >= 1.0",
        ),
        (
            {"AML__CASES__SUPPRESSION__HIBERNATION_MIN_FALSE_POSITIVES": "0"},
            "hibernation_min_false_positives must be >= 1",
        ),
    ],
)
def test_ac1_invalid_suppression_config_is_rejected(env: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(message)):
        load_settings(environ=env)


def test_ac1_suppression_version() -> None:
    assert supp().SUPPRESSION_VERSION == "suppression/v1"
    assert (supp().GOOD_GUY, supp().HIBERNATION) == ("GOOD_GUY", "HIBERNATION")


def test_ac1_ddl_170_is_registered_for_both_backends() -> None:
    duckdb = SCHEMA_SCRIPTS["duckdb"]
    assert DDL in duckdb
    assert duckdb.index(DDL) > duckdb.index("ddl/160_cases.sql")
    assert duckdb.index(DDL) < duckdb.index("ddl/050_customers_masked.sql")
    oracle = SCHEMA_SCRIPTS["oracle"]
    assert DDL in oracle
    assert oracle.index(DDL) > oracle.index("ddl/160_cases.sql")
    assert oracle.index(DDL) < oracle.index("ddl/050_security_objects.sql")
    for backend in ("duckdb", "oracle"):
        assert sql_file(DDL, backend) == SQL_ROOT / backend / "ddl" / "170_case_suppression.sql"
        assert sql_file(DDL, backend).exists()


def test_ac1_apply_schema_twice_creates_empty_good_guy_objects(duck: DuckDb) -> None:
    apply_schema(duck)
    apply_schema(duck)  # idempotent
    assert count(duck, "good_guy_list") == 0
    assert count(duck, "good_guy_current") == 0


# ------------------------------------------------------------------ AC2
def _entry(**override: Any) -> Any:
    fields: dict[str, Any] = {
        "entry_no": 1,
        "cif": "C05",
        "entry_id": "WL2",
        "case_id": "C-C05-20260630",
        "disposition_id": 1,
        "cleared_on": date(2026, 6, 30),
        "expires_on": date(2027, 6, 30),
        "customer_fingerprint": "fp-c05",
        "entry_fingerprint": "fp-wl2",
        "actor": "analyst01",
    }
    return supp().GoodGuyEntry(**{**fields, **override})


def _verdict(
    as_of: date = date(2026, 7, 1),
    customer: str | None = "fp-c05",
    entry: str | None = "fp-wl2",
    latest: int | None = 1,
    row: Any = "E",
) -> tuple[Any, ...]:
    v = supp().good_guy_verdict(
        _entry() if row == "E" else row,
        as_of=as_of,
        customer_fingerprint=customer,
        entry_fingerprint=entry,
        latest_disposition_id=latest,
    )
    return (v.suppress, v.lifted, v.retriggered, v.reason)


NONE_VERDICT = (False, False, False, None)


def test_ac2_no_entry_gives_the_empty_verdict() -> None:
    got = _verdict(row=None, latest=None)
    assert got == NONE_VERDICT
    v = supp().good_guy_verdict(
        None,
        as_of=date(2026, 7, 1),
        customer_fingerprint="fp-c05",
        entry_fingerprint="fp-wl2",
        latest_disposition_id=None,
    )
    assert v == supp().Verdict(False, False, False, None)


def test_ac2_unchanged_and_valid_is_suppressed() -> None:
    assert _verdict() == (
        True,
        False,
        False,
        "good-guy list: C05 x WL2 cleared on 2026-06-30 by analyst01 (case C-C05-20260630); "
        "valid until 2027-06-30; customer and watchlist entry unchanged",
    )


def test_ac2_expiry_day_itself_is_still_suppressed() -> None:
    got = _verdict(as_of=date(2027, 6, 30))
    assert got[:3] == (True, False, False)


def test_ac2_day_after_expiry_lifts_and_retriggers() -> None:
    assert _verdict(as_of=date(2027, 7, 1)) == (
        False,
        True,
        True,
        "good-guy entry for C05 x WL2 expired on 2027-06-30; alert re-raised",
    )


def test_ac2_customer_fingerprint_change_lifts() -> None:
    assert _verdict(customer="fp-c05-v2") == (
        False,
        True,
        True,
        "customer data of C05 changed since the clearance on 2026-06-30; alert re-raised",
    )


def test_ac2_entry_fingerprint_change_lifts() -> None:
    assert _verdict(entry="fp-wl2-v2") == (
        False,
        True,
        True,
        "watchlist entry WL2 changed since the clearance on 2026-06-30; alert re-raised",
    )


def test_ac2_missing_customer_fingerprint_counts_as_changed() -> None:
    got = _verdict(customer=None)
    assert got[:3] == (False, True, True)
    assert str(got[3]).startswith("customer data of C05 changed")


def test_ac2_missing_entry_fingerprint_counts_as_changed() -> None:
    got = _verdict(entry=None)
    assert got[:3] == (False, True, True)
    assert str(got[3]).startswith("watchlist entry WL2 changed")


def test_ac2_expiry_is_checked_before_data_changes() -> None:
    got = _verdict(as_of=date(2027, 7, 1), customer="fp-c05-v2")
    assert got[:3] == (False, True, True)
    assert str(got[3]).startswith("good-guy entry for C05 x WL2 expired")


def test_ac2_a_later_decision_takes_over() -> None:
    assert _verdict(latest=2) == NONE_VERDICT
    # even when the entry is expired or the data changed: the later decision is what counts
    assert _verdict(latest=2, as_of=date(2027, 7, 1), customer="fp-c05-v2") == NONE_VERDICT


# ------------------------------------------------------------------ AC6
def _pattern(**override: Any) -> Any:
    fields: dict[str, Any] = {
        "golden_customer_id": "G-C04",
        "rule_id": "HIGH_VELOCITY",
        "false_positives": 2,
        "cleared_on": date(2026, 3, 10),
        "max_amount_vnd": 120_000_000,
        "handled": frozenset({"k1", "k2"}),
    }
    return supp().HibernationPattern(**{**fields, **override})


def _hib(
    pattern: Any,
    when: datetime,
    amount: int,
    key: str = "k9",
) -> tuple[Any, ...]:
    cfg = load_settings(environ={}).cases.suppression
    v = supp().hibernation_verdict(pattern, item_key=key, event_ts=when, amount_vnd=amount, cfg=cfg)
    return (v.suppress, v.lifted, v.retriggered, v.reason)


def test_ac6_no_pattern_or_too_few_false_positives_is_the_empty_verdict() -> None:
    assert _hib(None, datetime(2026, 4, 10, 9), 1) == NONE_VERDICT
    assert _hib(_pattern(false_positives=1), datetime(2026, 4, 10, 9), 1) == NONE_VERDICT
    cfg = load_settings(environ={}).cases.suppression
    v = supp().hibernation_verdict(
        None, item_key="k9", event_ts=datetime(2026, 4, 10, 9), amount_vnd=1, cfg=cfg
    )
    assert v == supp().Verdict(False, False, False, None)


def test_ac6_handled_item_is_left_alone() -> None:
    got = _hib(_pattern(), datetime(2026, 4, 10, 9), 100_000_000, key="k1")
    assert got[0] is False
    assert got[1] is False


def test_ac6_last_second_of_the_sleep_is_suppressed() -> None:
    got = _hib(_pattern(), datetime(2026, 6, 8, 23, 59, 59), 180_000_000)
    assert got[0] is True
    assert got[2] is False
    assert isinstance(got[3], str)


def test_ac6_first_second_after_the_sleep_is_the_empty_verdict() -> None:
    assert _hib(_pattern(), datetime(2026, 6, 9, 0, 0, 0), 180_000_000) == NONE_VERDICT


def test_ac6_amount_above_the_ratio_lifts_without_retrigger() -> None:
    got = _hib(_pattern(), datetime(2026, 4, 10, 9), 180_000_001)
    assert got[:3] == (False, True, False)
    assert got[3] == (
        "hibernation of HIGH_VELOCITY on G-C04 lifted: amount 180,000,001 VND is above 1.5x "
        "the largest cleared alert (120,000,000 VND)"
    )


def test_ac6_suppress_reason_text() -> None:
    got = _hib(_pattern(), datetime(2026, 4, 10, 9), 150_000_000)
    assert got == (
        True,
        False,
        False,
        "hibernated: HIGH_VELOCITY on G-C04 was a false positive 2 time(s), last cleared on "
        "2026-03-10; suppressed until 2026-06-08; amount 150,000,000 VND is not above 1.5x "
        "the largest cleared alert (120,000,000 VND)",
    )


def test_ac6_alert_before_the_clear_date_is_suppressed() -> None:
    got = _hib(_pattern(), datetime(2026, 1, 5, 9), 100_000_000)
    assert got[0] is True


def test_ac6_zero_max_amount() -> None:
    zero = _pattern(max_amount_vnd=0)
    assert _hib(zero, datetime(2026, 4, 10, 9), 1)[:3] == (False, True, False)
    assert _hib(zero, datetime(2026, 4, 10, 9), 0)[0] is True


def test_ac6_replace_keeps_pattern_frozen() -> None:
    # the patterns are values: building a changed copy must not alter the original
    p = _pattern()
    assert replace(p, false_positives=1).false_positives == 1
    assert p.false_positives == 2
