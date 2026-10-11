"""Tier 2: turn a name score plus secondary identifiers into ALERT / REVIEW / AUTO_CLEARED.

``decide`` is pure. Rules run in a fixed order and the first that applies wins; every outcome
carries a human-readable ``reason`` so analysts (and the audit log) can see why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from aml.common.config import ScreeningConfig
from aml.screening.scoring import NameScore

ALERT, REVIEW, AUTO_CLEARED = "ALERT", "REVIEW", "AUTO_CLEARED"


@dataclass(frozen=True)
class Identifiers:
    dob: date | None = None
    dob_year: int | None = None  # customer: year of dob; watchlist: the dob_year column
    nationality: str | None = None
    gender: str | None = None  # watchlist Phase 1 has none -> always None there
    id_number: str | None = None  # watchlist Phase 1 has none -> always None there


@dataclass(frozen=True)
class Decision:
    decision: str  # ALERT | REVIEW | AUTO_CLEARED
    reason: str
    final_score: float  # name score after identifier discounts, rounded to 2
    dob_gap_years: int | None  # None when either side has no usable birth year


def _clean_id(value: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", value.upper()) if value else ""


def _birth_year_gap(customer: Identifiers, entry: Identifiers, as_of: date) -> int | None:
    """Gap in years; a missing or future customer DOB, or a missing list year, is unknown."""
    if customer.dob is None or customer.dob > as_of or entry.dob_year is None:
        return None
    return abs(customer.dob.year - entry.dob_year)


def _differs(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a != b


def decide(
    name: NameScore,
    customer: Identifiers,
    entry: Identifiers,
    cfg: ScreeningConfig,
    *,
    as_of: date,
) -> Decision | None:
    """Apply the six Tier 2 rules; ``None`` means the pair is not recorded."""
    if name.fuzzy < cfg.review_threshold:
        return None

    gap = _birth_year_gap(customer, entry, as_of)
    cust_id, entry_id = _clean_id(customer.id_number), _clean_id(entry.id_number)
    if cust_id and cust_id == entry_id:
        return Decision(ALERT, "ID number match (identical identity document number)", 100.0, gap)

    if name.score < cfg.review_threshold:
        head = "only common tokens matched" if name.common_only else "weak name match"
        return Decision(AUTO_CLEARED, f"{head} (name score {name.score:.2f})", name.score, gap)

    dob_text = "DOB unknown" if gap is None else f"DOB gap {gap}y"
    if gap is not None and gap > cfg.dob_clear_years:
        return Decision(
            AUTO_CLEARED,
            f"DOB mismatch > {cfg.dob_clear_years}y (name score {name.score:.2f}, {dob_text})",
            name.score,
            gap,
        )

    final = name.score
    notes = [dob_text]
    if gap is not None and gap > cfg.dob_tolerance_years:
        final -= cfg.dob_gap_discount
    if _differs(customer.nationality, entry.nationality):
        final -= cfg.nationality_mismatch_discount
        notes.append(f"nationality {customer.nationality} vs {entry.nationality}")
    if _differs(customer.gender, entry.gender):
        final -= cfg.gender_mismatch_discount
        notes.append(f"gender {customer.gender} vs {entry.gender}")
    final = round(final, 2)

    if final >= cfg.alert_threshold:
        outcome, head = ALERT, "strong name match"
    elif final >= cfg.review_threshold:
        outcome, head = REVIEW, "possible name match"
    else:
        outcome, head = AUTO_CLEARED, "discounted below review threshold"
    detail = f"name score {name.score:.2f}, final score {final:.2f}, " + ", ".join(notes)
    return Decision(outcome, f"{head} ({detail})", final, gap)
