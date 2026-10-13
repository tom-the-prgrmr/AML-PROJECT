"""The two suppression rules as pure functions: no database, no clock, no audit.

A rule looks at one item and at what a person decided before, and answers with a `Verdict`.
`aml.cases.suppression` reads the data, calls these functions and writes the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from aml.common.config import SuppressionConfig

__all__ = [
    "GOOD_GUY",
    "HIBERNATION",
    "SUPPRESSION_VERSION",
    "GoodGuyEntry",
    "HibernationPattern",
    "Outcome",
    "Verdict",
    "good_guy_verdict",
    "hibernation_verdict",
]

SUPPRESSION_VERSION = "suppression/v1"
GOOD_GUY, HIBERNATION = "GOOD_GUY", "HIBERNATION"


@dataclass(frozen=True)
class GoodGuyEntry:
    """One row of ``good_guy_list``: a screening pair cleared as a false positive."""

    entry_no: int
    cif: str
    entry_id: str
    case_id: str
    disposition_id: int
    cleared_on: date
    expires_on: date
    customer_fingerprint: str
    entry_fingerprint: str
    actor: str


@dataclass(frozen=True)
class Verdict:
    suppress: bool
    lifted: (
        bool  # an entry or pattern exists but does not apply: expired, data or behaviour changed
    )
    retriggered: bool  # the item returns to a case that was closed -> that case becomes REOPENED
    reason: str | None  # None when no entry or pattern is involved


@dataclass(frozen=True)
class HibernationPattern:
    """What people cleared as false positives for one (golden customer, rule)."""

    golden_customer_id: str
    rule_id: str
    false_positives: int  # distinct item_key cleared
    cleared_on: date  # latest clearance
    max_amount_vnd: int  # largest cleared alert
    handled: frozenset[str]  # item_key already inside a cleared case


@dataclass(frozen=True)
class Outcome:
    """A verdict with the rule that produced it and the two dates shown in the audit event."""

    rule: str
    verdict: Verdict
    cleared_on: date
    until: date


_NONE = Verdict(suppress=False, lifted=False, retriggered=False, reason=None)


def good_guy_verdict(
    entry: GoodGuyEntry | None,
    *,
    as_of: date,
    customer_fingerprint: str | None,
    entry_fingerprint: str | None,
    latest_disposition_id: int | None,
) -> Verdict:
    """Apply the newest good-guy row of a pair; the first condition that matches wins."""
    if entry is None:
        return _NONE
    # A later decision on the case (or none at all) replaces the clearance that made this row.
    if latest_disposition_id != entry.disposition_id:
        return _NONE
    pair = f"{entry.cif} x {entry.entry_id}"
    if as_of > entry.expires_on:
        reason = f"good-guy entry for {pair} expired on {entry.expires_on.isoformat()}"
    elif customer_fingerprint != entry.customer_fingerprint:  # a missing fingerprint counts too
        reason = (
            f"customer data of {entry.cif} changed since the clearance on "
            f"{entry.cleared_on.isoformat()}"
        )
    elif entry_fingerprint != entry.entry_fingerprint:
        reason = (
            f"watchlist entry {entry.entry_id} changed since the clearance on "
            f"{entry.cleared_on.isoformat()}"
        )
    else:
        return Verdict(
            suppress=True,
            lifted=False,
            retriggered=False,
            reason=(
                f"good-guy list: {pair} cleared on {entry.cleared_on.isoformat()} by "
                f"{entry.actor} (case {entry.case_id}); valid until "
                f"{entry.expires_on.isoformat()}; customer and watchlist entry unchanged"
            ),
        )
    return Verdict(
        suppress=False, lifted=True, retriggered=True, reason=f"{reason}; alert re-raised"
    )


def hibernation_verdict(
    pattern: HibernationPattern | None,
    *,
    item_key: str,
    event_ts: datetime,
    amount_vnd: int,
    cfg: SuppressionConfig,
) -> Verdict:
    """Apply a (golden customer, rule) pattern to a new alert; the first match wins."""
    if pattern is None or pattern.false_positives < cfg.hibernation_min_false_positives:
        return _NONE
    if item_key in pattern.handled:  # the old alert stays in its closed case
        return _NONE
    until = pattern.cleared_on + timedelta(days=cfg.hibernation_days)
    if event_ts.date() > until:
        return _NONE
    where = f"{pattern.rule_id} on {pattern.golden_customer_id}"
    ratio = cfg.material_change_ratio
    largest = f"the largest cleared alert ({pattern.max_amount_vnd:,} VND)"
    # Decimal of the printed ratio: a float product (1.15 x 3 000 000) can land just below the
    # exact limit, and an alert equal to ratio x largest must still sleep.
    if amount_vnd > Decimal(str(ratio)) * pattern.max_amount_vnd:
        return Verdict(
            suppress=False,
            lifted=True,
            retriggered=False,
            reason=(
                f"hibernation of {where} lifted: amount {amount_vnd:,} VND is above {ratio}x "
                f"{largest}"
            ),
        )
    return Verdict(
        suppress=True,
        lifted=False,
        retriggered=False,
        reason=(
            f"hibernated: {where} was a false positive {pattern.false_positives} time(s), last "
            f"cleared on {pattern.cleared_on.isoformat()}; suppressed until {until.isoformat()}; "
            f"amount {amount_vnd:,} VND is not above {ratio}x {largest}"
        ),
    )
