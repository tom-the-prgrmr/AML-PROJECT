"""Human review of a screening hit.

A review is one ``audit_log`` row beside the system decision. It never changes the result row, and
it never closes, clears or files anything: the model and the rules only rank, people decide.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database

TRUE_MATCH = "TRUE_MATCH"
FALSE_MATCH = "FALSE_MATCH"
REVIEW_DECISIONS = (TRUE_MATCH, FALSE_MATCH)
VERSION = "screening/v1"
ENTITY_TYPE = "screening_match"


class ScreeningReviewError(RuntimeError):
    """The review cannot be recorded (system actor, or the hit is not a current result)."""


@dataclass(frozen=True)
class ScreeningReview:
    cif: str
    entry_id: str
    decision: str
    reason: str
    actor: str
    decided_on: date
    run_id: int
    system_decision: str


def _details(value: Any) -> dict[str, Any]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {}
    return value if isinstance(value, dict) else json.loads(str(value))


def record_review(
    db: Database,
    settings: Settings,
    cif: str,
    entry_id: str,
    decision: str,
    *,
    reason: str,
    actor: str,
    decided_on: date | None = None,
) -> ScreeningReview:
    """Write the review of one current hit as one audit row; return what was recorded."""
    if decision not in REVIEW_DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(REVIEW_DECISIONS)}")
    if actor == settings.audit.system_actor:
        raise ScreeningReviewError("a screening review needs a human actor")
    df = db.query_df(
        "SELECT run_id, decision, final_score, list_type FROM screening_current "
        f"WHERE cif = {_literal(cif)} AND entry_id = {_literal(entry_id)}"
    )
    df.columns = [str(c).lower() for c in df.columns]
    if df.empty:
        raise ScreeningReviewError(f"unknown screening hit {cif}:{entry_id}")
    row = df.iloc[0]
    day = decided_on or settings.data.reference_date
    run_id, system_decision = int(row["run_id"]), str(row["decision"])
    audit(
        db,
        module="screening",
        entity_type=ENTITY_TYPE,
        entity_id=f"{cif}:{entry_id}",
        decision=decision,
        reason=reason,
        version=VERSION,
        actor=actor,
        details={
            "run_id": run_id,
            "system_decision": system_decision,
            "final_score": float(row["final_score"]),
            "list_type": None if pd.isna(row["list_type"]) else str(row["list_type"]),
            "decided_on": day.isoformat(),
            "origin": "HUMAN",
        },
    )
    return ScreeningReview(cif, entry_id, decision, reason, actor, day, run_id, system_decision)


def _literal(value: str) -> str:
    """A SQL string literal (the same text on DuckDB and Oracle, whose bind styles differ)."""
    return "'" + value.replace("'", "''") + "'"


def latest_reviews(db: Database) -> dict[tuple[str, str], ScreeningReview]:
    """The newest review of every ``(cif, entry_id)``; a later row supersedes an earlier one."""
    df = db.query_df(
        "SELECT entity_id, decision, reason, actor, details FROM audit_log "
        f"WHERE module = 'screening' AND entity_type = '{ENTITY_TYPE}' "
        "AND decision IN ('TRUE_MATCH', 'FALSE_MATCH') ORDER BY audit_id"
    )
    df.columns = [str(c).lower() for c in df.columns]
    out: dict[tuple[str, str], ScreeningReview] = {}
    for _, r in df.iterrows():
        cif, _, entry_id = str(r["entity_id"]).partition(":")
        try:
            d = _details(r["details"])
            review = ScreeningReview(
                cif,
                entry_id,
                str(r["decision"]),
                str(r["reason"]),
                str(r["actor"]),
                date.fromisoformat(d["decided_on"]),
                int(d["run_id"]),
                str(d["system_decision"]),
            )
        except (KeyError, TypeError, ValueError):
            continue  # an audit row without review details is not a review: skip it, do not fail
        out[(cif, entry_id)] = review
    return out
