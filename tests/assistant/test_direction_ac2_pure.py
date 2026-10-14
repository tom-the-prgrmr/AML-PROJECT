"""AC2 for specs/assistant-direction-check.md: ISSUES, is_speculative, transfer_sides."""

from __future__ import annotations

from dataclasses import replace

import pytest

from .an_helpers import X1, X2
from .dir_helpers import A315, A941, D1, D4, S_CAN, S_IN, S_SPEC2, facts, validation


def test_dir_ac2_issues_order() -> None:
    """Given the module, When ISSUES is read, Then the two new codes follow date_not_in_evidence."""
    assert validation().ISSUES == (
        "no_citation",
        "unknown_citation",
        "amount_not_in_evidence",
        "date_not_in_evidence",
        "direction_mismatch",
        "speculative",
        "verdict_language",
    )


@pytest.mark.parametrize(
    "text",
    [
        S_SPEC2,
        "Tài khoản A3154676584 có thể là tài khoản trung gian.",
        "Tai khoan nay co le la tai khoan mule.",
        "Account A9418747931 is possibly a mule account.",
        "This might be layering.",
    ],
)
def test_dir_ac2_is_speculative_true(text: str) -> None:
    """Given a hedged sentence, When is_speculative runs, Then True."""
    assert facts().is_speculative(text) is True


@pytest.mark.parametrize(
    "text",
    [
        S_IN,
        S_CAN,
        "Account A3154676584 sent 153,936,000 VND to account A9418747931 in May 2026.",
        "Khách hàng có hành vi đáng ngờ.",
    ],
)
def test_dir_ac2_is_speculative_false(text: str) -> None:
    """Given a plain sentence, When is_speculative runs, Then False."""
    assert facts().is_speculative(text) is False


def test_dir_ac2_transfer_sides() -> None:
    """Given evidence items, When transfer_sides runs, Then the (account, role) pairs are exact."""
    ts = validation().transfer_sides
    assert ts(D1) == {(A315, "src"), (A941, "dst")}
    assert ts(X1) == {("A01", "dst")}  # the None side of a cash deposit gives no pair
    assert ts(D4) == {(A941, "dst")}
    assert ts(replace(D4, data={**D4.data, "direction": "IN"})) == {(A941, "src")}
    assert ts(X2) == frozenset()
