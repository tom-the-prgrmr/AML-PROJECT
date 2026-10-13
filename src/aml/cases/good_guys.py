"""Good-guy writer: when a case is cleared as a false positive, remember its screening pairs.

Called by `record_disposition`. The rows are read back by `aml.cases.suppression`, which applies
`good_guy_verdict` to them; this module only writes.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from aml.cases.suppression_rules import SUPPRESSION_VERSION
from aml.cases.values import is_case_id, lower_columns, plain_date, whole
from aml.common.audit import AuditEvent, audit_many
from aml.common.config import Settings
from aml.common.db import Database
from aml.screening.state import CUSTOMER, ENTRY, read_state

__all__ = ["add_good_guys"]

ACTIVE, SOURCE_SCREENING = "ACTIVE", "SCREENING"


def _read(db: Database, sql: str) -> pd.DataFrame:
    return lower_columns(db.query_df(sql))


def add_good_guys(db: Database, settings: Settings, case_id: str, disposition_id: int) -> int:
    """Add a good-guy row for each ACTIVE screening pair of a case cleared as a false positive.

    The pairs come from the case snapshot the disposition refers to; the fingerprints from
    ``screening_state`` now. A pair without both fingerprints is skipped and audited. Return the
    number of rows added.
    """
    if not is_case_id(case_id):
        raise ValueError(f"unknown case_id {case_id}")
    disposition = _read(
        db,
        "SELECT run_id, actor, decided_on FROM case_dispositions "
        f"WHERE disposition_id = {int(disposition_id)} AND case_id = '{case_id}'",
    )
    if disposition.empty:
        raise ValueError(f"no disposition {disposition_id} for case {case_id}")
    run_id, actor = whole(disposition["run_id"].iloc[0]), str(disposition["actor"].iloc[0])
    cleared_on = plain_date(disposition["decided_on"].iloc[0])
    expires_on = cleared_on + timedelta(days=settings.cases.suppression.good_guy_days)
    pairs = _read(
        db,
        "SELECT DISTINCT cif, entry_id FROM case_alerts "
        f"WHERE run_id = {run_id} AND case_id = '{case_id}' AND source = '{SOURCE_SCREENING}' "
        f"AND status = '{ACTIVE}' ORDER BY cif, entry_id",
    )
    state = read_state(db)
    top = _read(db, "SELECT COALESCE(MAX(entry_no), 0) AS n FROM good_guy_list")
    next_no = 1 + whole(top["n"].iloc[0])
    rows: list[dict[str, object]] = []
    events: list[AuditEvent] = []
    for cif_, entry_ in zip(pairs["cif"], pairs["entry_id"], strict=True):
        cif, entry_id = str(cif_), str(entry_)
        customer_fp, entry_fp = state[CUSTOMER].get(cif), state[ENTRY].get(entry_id)
        if customer_fp is None or entry_fp is None:
            missing = f"customer {cif}" if customer_fp is None else f"entry {entry_id}"
            events.append(
                _good_guy_event(
                    cif,
                    entry_id,
                    actor,
                    "GOOD_GUY_SKIPPED",
                    f"{cif} x {entry_id} not added to the good-guy list: no screening "
                    f"fingerprint for {missing}",
                    {"case_id": case_id, "disposition_id": disposition_id},
                )
            )
            continue
        rows.append(
            _row(
                next_no,
                cif,
                entry_id,
                case_id,
                disposition_id,
                actor,
                cleared_on,
                expires_on,
                customer_fp,
                entry_fp,
            )
        )
        events.append(_added_event(rows[-1], "cleared as a false positive in case"))
        next_no += 1
    seen = {(str(c), str(e)) for c, e in zip(pairs["cif"], pairs["entry_id"], strict=True)}
    for held in _held(db, case_id, seen):
        fresh = (
            cleared_on <= held["expires_on"]
            and state[CUSTOMER].get(str(held["cif"])) == held["customer_fingerprint"]
            and state[ENTRY].get(str(held["entry_id"])) == held["entry_fingerprint"]
        )
        if fresh:  # still valid and unchanged: renewed from the new decision date
            rows.append(
                {
                    **held,
                    "entry_no": next_no,
                    "disposition_id": disposition_id,
                    "cleared_on": cleared_on,
                    "expires_on": expires_on,
                    "actor": actor,
                }
            )
            events.append(_added_event(rows[-1], "cleared again as a false positive in case"))
        else:  # carried with its old dates and fingerprints so the next run lifts it, with a reason
            rows.append(
                {**held, "entry_no": next_no, "disposition_id": disposition_id, "actor": actor}
            )
            events.append(
                _good_guy_event(
                    str(held["cif"]),
                    str(held["entry_id"]),
                    actor,
                    "GOOD_GUY_CARRIED",
                    f"{held['cif']} x {held['entry_id']} not renewed when case {case_id} was "
                    "cleared again: expired or changed since the first clearance; the next "
                    "case run re-raises it",
                    {"entry_no": next_no, "case_id": case_id, "disposition_id": disposition_id},
                )
            )
        next_no += 1
    if rows:
        db.insert_df("good_guy_list", pd.DataFrame(rows))
    audit_many(db, events)
    return sum(1 for e in events if e.decision == "GOOD_GUY_ADDED")


def _row(
    entry_no: int,
    cif: str,
    entry_id: str,
    case_id: str,
    disposition_id: int,
    actor: str,
    cleared_on: date,
    expires_on: date,
    customer_fp: str,
    entry_fp: str,
) -> dict[str, object]:
    return {
        "entry_no": entry_no,
        "cif": cif,
        "entry_id": entry_id,
        "case_id": case_id,
        "disposition_id": disposition_id,
        "cleared_on": cleared_on,
        "expires_on": expires_on,
        "customer_fingerprint": customer_fp,
        "entry_fingerprint": entry_fp,
        "actor": actor,
        "created_ts": datetime.now(UTC).replace(tzinfo=None),
    }


def _added_event(row: dict[str, object], what: str) -> AuditEvent:
    expires = row["expires_on"]
    assert isinstance(expires, date) and isinstance(row["cleared_on"], date)
    return _good_guy_event(
        str(row["cif"]),
        str(row["entry_id"]),
        str(row["actor"]),
        "GOOD_GUY_ADDED",
        f"{row['cif']} x {row['entry_id']} {what} {row['case_id']}; suppressed until "
        f"{expires.isoformat()} unless the customer or the watchlist entry changes",
        {
            "entry_no": row["entry_no"],
            "case_id": row["case_id"],
            "disposition_id": row["disposition_id"],
            "cleared_on": row["cleared_on"].isoformat(),
            "expires_on": expires.isoformat(),
        },
    )


def _held(db: Database, case_id: str, seen: set[tuple[str, str]]) -> list[dict[str, object]]:
    """Current good-guy rows of this case whose pair is not ACTIVE in the snapshot.

    Those items are SUPPRESSED, so they are absent from the snapshot; clearing the case again must
    deal with them here, or the newer disposition would silently end their suppression.
    """
    df = _read(
        db,
        "SELECT cif, entry_id, case_id, cleared_on, expires_on, customer_fingerprint, "
        f"entry_fingerprint FROM good_guy_current WHERE case_id = '{case_id}' "
        "ORDER BY cif, entry_id",
    )
    out: list[dict[str, object]] = []
    for r in df.itertuples():
        if (str(r.cif), str(r.entry_id)) in seen:
            continue
        out.append(
            {
                "cif": str(r.cif),
                "entry_id": str(r.entry_id),
                "case_id": case_id,
                "cleared_on": plain_date(r.cleared_on),
                "expires_on": plain_date(r.expires_on),
                "customer_fingerprint": str(r.customer_fingerprint),
                "entry_fingerprint": str(r.entry_fingerprint),
                "created_ts": datetime.now(UTC).replace(tzinfo=None),
            }
        )
    return out


def _good_guy_event(
    cif: str, entry_id: str, actor: str, decision: str, reason: str, details: dict[str, object]
) -> AuditEvent:
    return AuditEvent(
        module="cases",
        entity_type="good_guy",
        entity_id=f"{cif}:{entry_id}",
        decision=decision,
        reason=reason,
        version=SUPPRESSION_VERSION,
        actor=actor,
        details=details,
    )
