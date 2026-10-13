"""Human decisions on cases. Append-only: a later decision replaces an earlier one in the view.

Only people write here. The status of a case (CLOSED / REOPENED) is derived by `run_cases` on its
next run; this module never touches the ``cases`` table.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from aml.cases.runner import CASES_VERSION, CaseError
from aml.cases.values import is_case_id
from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database

__all__ = [
    "DISPOSITIONS",
    "FALSE_POSITIVE",
    "HUMAN",
    "SIMULATED",
    "SUSPICIOUS",
    "record_disposition",
]

SUSPICIOUS, FALSE_POSITIVE = "SUSPICIOUS", "FALSE_POSITIVE"
DISPOSITIONS = (SUSPICIOUS, FALSE_POSITIVE)
HUMAN, SIMULATED = "HUMAN", "SIMULATED"  # origin


def _scalar(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def record_disposition(
    db: Database,
    settings: Settings,
    case_id: str,
    disposition: str,
    *,
    reason: str,
    actor: str,
    decided_on: date | None = None,
    origin: str = HUMAN,
) -> int:
    """Store a decision on a case and audit it; return the new ``disposition_id``."""
    if disposition not in DISPOSITIONS:
        raise ValueError(
            f"disposition must be one of {', '.join(DISPOSITIONS)}, got {disposition!r}"
        )
    if not reason or not reason.strip():
        raise ValueError("a disposition needs a reason")
    if origin == HUMAN and actor == settings.audit.system_actor:
        raise CaseError("a disposition needs a human actor")
    if not is_case_id(case_id):  # the id comes from a user; the two backends bind differently
        raise CaseError(f"unknown case_id {case_id}")
    run_id = _scalar(  # only published runs: a run that died before `case_runs` does not count
        db,
        "SELECT COALESCE(MAX(run_id), 0) FROM cases "
        f"WHERE case_id = '{case_id}' AND run_id IN (SELECT run_id FROM case_runs)",
    )
    if run_id == 0:
        raise CaseError(f"unknown case_id {case_id}")

    decided_on = decided_on or settings.data.reference_date
    disposition_id = 1 + _scalar(
        db, "SELECT COALESCE(MAX(disposition_id), 0) FROM case_dispositions"
    )
    db.insert_df(
        "case_dispositions",
        pd.DataFrame(
            [
                {
                    "disposition_id": disposition_id,
                    "case_id": case_id,
                    "run_id": run_id,
                    "disposition": disposition,
                    "reason": reason,
                    "actor": actor,
                    "origin": origin,
                    "decided_on": decided_on,
                    "decided_ts": datetime.now(UTC).replace(tzinfo=None),
                }
            ]
        ),
    )
    audit(
        db,
        module="cases",
        entity_type="case",
        entity_id=case_id,
        decision=disposition,
        reason=reason,
        version=CASES_VERSION,
        actor=actor,
        details={
            "disposition_id": disposition_id,
            "run_id": run_id,
            "origin": origin,
            "decided_on": decided_on.isoformat(),
        },
    )
    return disposition_id
