"""AC3-AC5 for specs/screening-tiers-eval.md: Tier 2 `decide` (reasons, DOB, other identifiers)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from .helpers import screening_cfg
from .helpers_3b import N, cust, decide, entry, ident


@pytest.fixture
def cfg() -> Any:
    return screening_cfg()


def test_ac3_below_review_fuzzy_is_not_recorded(cfg: Any) -> None:
    assert decide(N(74.88, 44.45), cust(), entry(1971), cfg) is None


def test_ac3_only_common_tokens_is_auto_cleared(cfg: Any) -> None:
    d = decide(N(97.08, 45.14, common_only=True), cust(), entry(1971), cfg)
    assert d.decision == "AUTO_CLEARED"
    assert d.reason.startswith("only common tokens matched")
    assert d.final_score == 45.14


def test_ac3_weak_name_match_is_auto_cleared(cfg: Any) -> None:
    d = decide(N(97.08, 45.14), cust(), entry(1971), cfg)
    assert d.decision == "AUTO_CLEARED"
    assert d.reason.startswith("weak name match")
    assert d.final_score == 45.14


@pytest.mark.parametrize(("fuzzy", "score"), [(75.0, 75.0), (95.0, 89.99)])
def test_ac3_review_band(cfg: Any, fuzzy: float, score: float) -> None:
    d = decide(N(fuzzy, score), cust(), entry(1971), cfg)
    assert d.decision == "REVIEW"
    assert d.reason.startswith("possible name match")
    assert d.final_score == score


@pytest.mark.parametrize("score", [90.0, 100.0])
def test_ac3_alert_band(cfg: Any, score: float) -> None:
    d = decide(N(score, score), cust(), entry(1971), cfg)
    assert d.decision == "ALERT"
    assert d.reason.startswith("strong name match")
    assert d.final_score == score
    assert d.dob_gap_years == 0


def test_ac4_dob_gap_rules(cfg: Any) -> None:
    n = N(100.0, 100.0)
    cases = [
        (1972, "ALERT", 100.0, 1),
        (1973, "REVIEW", 85.0, 2),
        (1976, "REVIEW", 85.0, 5),
        (1977, "AUTO_CLEARED", 100.0, 6),
    ]
    for year, decision, final, gap in cases:
        d = decide(n, cust(), entry(year), cfg)
        assert (d.decision, d.final_score, d.dob_gap_years) == (decision, final, gap), year
    cleared = decide(n, cust(), entry(1977), cfg)
    assert cleared.reason.startswith("DOB mismatch > 5y")


def test_ac4_unknown_entry_year_is_alert_with_no_gap(cfg: Any) -> None:
    d = decide(N(100.0, 100.0), cust(), entry(None), cfg)
    assert d.decision == "ALERT"
    assert d.dob_gap_years is None


def test_ac4_same_year_different_day_counts_as_gap_zero(cfg: Any) -> None:
    c = cust(dob=date(1971, 8, 30), dob_year=1971)
    d = decide(N(100.0, 100.0), c, entry(1971), cfg)
    assert d.decision == "ALERT"
    assert d.dob_gap_years == 0


@pytest.mark.parametrize("dob", [date(2033, 1, 20), None])
def test_ac4_future_or_missing_customer_dob_is_unknown(cfg: Any, dob: date | None) -> None:
    customer = ident(dob=dob, dob_year=dob.year if dob else None, nationality="VN")
    d = decide(N(100.0, 100.0), customer, entry(1951), cfg)
    assert d.decision == "ALERT"
    assert d.final_score == 100.0
    assert d.dob_gap_years is None


def test_ac5_nationality_mismatch_discount(cfg: Any) -> None:
    n = N(100.0, 100.0)
    d = decide(n, cust(), ident(dob_year=1971, nationality="RU"), cfg)
    assert (d.decision, d.final_score) == ("REVIEW", 85.0)
    assert "nationality VN vs RU" in d.reason
    d = decide(n, cust(), ident(dob_year=1973, nationality="RU"), cfg)
    assert (d.decision, d.final_score) == ("AUTO_CLEARED", 70.0)
    assert d.reason.startswith("discounted below review threshold")


def test_ac5_missing_nationality_is_ignored(cfg: Any) -> None:
    ent = ident(dob_year=1971, nationality="RU")
    d = decide(N(100.0, 100.0), cust(nationality=None), ent, cfg)
    assert (d.decision, d.final_score) == ("ALERT", 100.0)


def test_ac5_gender_mismatch_discount(cfg: Any) -> None:
    n = N(100.0, 100.0)
    c = cust(gender="M")
    d = decide(n, c, ident(dob_year=1971, nationality="VN", gender="F"), cfg)
    assert (d.decision, d.final_score) == ("REVIEW", 85.0)
    d = decide(n, c, ident(dob_year=1971, nationality="VN", gender=None), cfg)
    assert d.decision == "ALERT"


def test_ac5_id_number_match_overrides_weak_name_and_dob(cfg: Any) -> None:
    n = N(80.0, 60.0)
    c = cust(id_number="B1234567")
    d = decide(n, c, ident(dob_year=1991, nationality="RU", id_number="b-1234567"), cfg)
    assert d.decision == "ALERT"
    assert d.reason.startswith("ID number match")
    assert d.final_score == 100.0


def test_ac5_different_id_number_has_no_effect(cfg: Any) -> None:
    n = N(80.0, 60.0)
    c = cust(id_number="B1234567")
    d = decide(n, c, ident(dob_year=1991, nationality="RU", id_number="C7654321"), cfg)
    assert d.decision == "AUTO_CLEARED"
    assert d.reason.startswith("weak name match")
