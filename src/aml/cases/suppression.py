"""Item-level suppression inside `run_cases`: read what people decided, apply the pure rules.

``evaluate_suppression`` writes nothing; it returns the items with their verdicts and
`suppression_events` turns them into audit events. ``add_good_guys`` (in `aml.cases.good_guys`) is
the one writer: it runs when a case is cleared as a false positive; hibernation lives in
`aml.cases.hibernation`. The rules themselves live in
`aml.cases.suppression_rules` and are re-exported here. Suppression never closes a case, never
touches the source alerts and never writes a disposition: people do that.

This module must not import `runner` or `dispositions` (both import it).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from aml.cases.good_guys import add_good_guys
from aml.cases.hibernation import hibernation_outcomes
from aml.cases.suppression_rules import (
    GOOD_GUY,
    HIBERNATION,
    SUPPRESSION_VERSION,
    GoodGuyEntry,
    HibernationPattern,
    Outcome,
    Verdict,
    good_guy_verdict,
    hibernation_verdict,
)
from aml.cases.values import lower_columns, plain_date, whole
from aml.common.audit import AuditEvent
from aml.common.config import Settings
from aml.common.db import Database
from aml.screening.state import CUSTOMER, ENTRY, read_state

__all__ = [
    "GOOD_GUY",
    "HIBERNATION",
    "SUPPRESSION_VERSION",
    "GoodGuyEntry",
    "HibernationPattern",
    "Outcome",
    "Verdict",
    "add_good_guys",
    "count_by_rule",
    "evaluate_suppression",
    "good_guy_verdict",
    "hibernation_outcomes",
    "hibernation_verdict",
    "suppression_events",
]

ACTIVE, SUPPRESSED = "ACTIVE", "SUPPRESSED"
SOURCE_SCREENING = "SCREENING"
# Columns `evaluate_suppression` adds besides the four stored in ``case_alerts`` (status,
# suppression_rule, suppression_reason, retriggered): they only feed the audit events.
_AUDIT_COLUMNS = ("lift_rule", "lift_reason", "cleared_on", "until")


def _read(db: Database, sql: str) -> pd.DataFrame:
    return lower_columns(db.query_df(sql))


def _load_good_guys(db: Database) -> dict[tuple[str, str], GoodGuyEntry]:
    df = _read(db, "SELECT * FROM good_guy_current")
    return {
        (str(r.cif), str(r.entry_id)): GoodGuyEntry(
            entry_no=whole(r.entry_no),
            cif=str(r.cif),
            entry_id=str(r.entry_id),
            case_id=str(r.case_id),
            disposition_id=whole(r.disposition_id),
            cleared_on=plain_date(r.cleared_on),
            expires_on=plain_date(r.expires_on),
            customer_fingerprint=str(r.customer_fingerprint),
            entry_fingerprint=str(r.entry_fingerprint),
            actor=str(r.actor),
        )
        for r in df.itertuples()
    }


def _good_guy_outcomes(db: Database, items: pd.DataFrame, as_of: date) -> dict[int, Outcome]:
    """Screening items whose pair has a good-guy row that suppresses them or was lifted."""
    screening = items[items["source"] == SOURCE_SCREENING]
    if screening.empty:
        return {}
    entries = _load_good_guys(db)
    decisions = _read(db, "SELECT case_id, disposition_id FROM case_dispositions_current")
    latest = {
        str(c): whole(d)
        for c, d in zip(decisions["case_id"], decisions["disposition_id"], strict=True)
    }
    state = read_state(db)
    out: dict[int, Outcome] = {}
    for idx, cif, entry_id in zip(
        screening.index, screening["cif"], screening["entry_id"], strict=True
    ):
        entry = entries.get((str(cif), str(entry_id)))
        if entry is None:
            continue
        verdict = good_guy_verdict(
            entry,
            as_of=as_of,
            customer_fingerprint=state[CUSTOMER].get(str(cif)),
            entry_fingerprint=state[ENTRY].get(str(entry_id)),
            latest_disposition_id=latest.get(entry.case_id),
        )
        if verdict.suppress or verdict.lifted:
            out[int(idx)] = Outcome(GOOD_GUY, verdict, entry.cleared_on, entry.expires_on)
    return out


def evaluate_suppression(
    db: Database, settings: Settings, items: pd.DataFrame, *, as_of: date
) -> pd.DataFrame:
    """Return the items with ``status``, ``suppression_rule``, ``suppression_reason`` and
    ``retriggered`` (stored in ``case_alerts``), plus ``lifted`` and the audit columns
    ``lift_rule``, ``lift_reason``, ``cleared_on``, ``until``. Reads only; writes nothing."""
    out = items.reset_index(drop=True)
    out["status"] = ACTIVE
    out["suppression_rule"] = pd.Series([None] * len(out), dtype=object)
    out["suppression_reason"] = pd.Series([None] * len(out), dtype=object)
    out["retriggered"] = 0
    out["lifted"] = 0
    for column in _AUDIT_COLUMNS:
        out[column] = pd.Series([None] * len(out), dtype=object)
    # The rules cover disjoint sources (SCREENING vs RULE/NETWORK), so their keys never collide.
    outcomes = _good_guy_outcomes(db, out, as_of) | hibernation_outcomes(db, settings, out)
    for idx, o in outcomes.items():
        if o.verdict.suppress:
            out.loc[idx, "status"] = SUPPRESSED
            out.loc[idx, "suppression_rule"] = o.rule
            out.loc[idx, "suppression_reason"] = o.verdict.reason
        else:
            out.loc[idx, "lifted"] = 1
            out.loc[idx, "retriggered"] = int(o.verdict.retriggered)
            out.loc[idx, "lift_rule"] = o.rule
            out.loc[idx, "lift_reason"] = o.verdict.reason
        out.loc[idx, "cleared_on"] = o.cleared_on
        out.loc[idx, "until"] = o.until
    return out


def count_by_rule(items: pd.DataFrame) -> dict[str, int]:
    """SUPPRESSED items per rule; both rules are always present, even with 0."""
    rules = items.loc[items["status"] == SUPPRESSED, "suppression_rule"]
    return {rule: int((rules == rule).sum()) for rule in (GOOD_GUY, HIBERNATION)}


def suppression_events(run_id: int, items: pd.DataFrame) -> list[AuditEvent]:
    """One event per item suppressed and one per item lifted in this run."""
    events = []
    for r in items.sort_values(["golden_customer_id", "item_key"]).itertuples():
        if r.status == SUPPRESSED:
            decision, rule, reason = SUPPRESSED, r.suppression_rule, r.suppression_reason
        elif r.lifted:
            decision, rule, reason = "SUPPRESSION_LIFTED", r.lift_rule, r.lift_reason
        else:
            continue
        events.append(
            AuditEvent(
                module="cases",
                entity_type="alert_item",
                entity_id=f"{r.alert_ref}@{r.golden_customer_id}"[:100],  # audit_log.entity_id
                decision=decision,
                reason=reason,
                version=SUPPRESSION_VERSION,
                details={
                    "run_id": run_id,
                    "item_key": r.item_key,
                    "rule": rule,
                    "source": r.source,
                    "rule_id": r.rule_id,
                    "cleared_on": plain_date(r.cleared_on).isoformat(),
                    "until": plain_date(r.until).isoformat(),
                },
            )
        )
    return events
