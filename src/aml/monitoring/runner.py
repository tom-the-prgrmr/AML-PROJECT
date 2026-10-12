"""Monitoring run: execute the rule SQL, store alerts with evidence, audit every one."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aml.common.config import Settings
from aml.common.db import Database
from aml.monitoring.detect import Detection, detect
from aml.monitoring.recording import AlertRecord, RuleRun, record_run
from aml.monitoring.rules import RULES, rule_params

__all__ = ["MonitoringError", "MonitoringRun", "run_monitoring"]

SOURCE_RULE = "RULE"
ROLE_SUBJECT = "SUBJECT"


class MonitoringError(RuntimeError):
    """Monitoring cannot run with the data it was given."""


@dataclass(frozen=True)
class MonitoringRun:
    run_id: int
    as_of: date
    alerts: int
    evidence: int  # alert_evidence rows of this run
    by_rule: dict[str, int]  # rule_id -> alerts, all rules, zeros included


def _check_data(db: Database) -> None:
    try:
        n = int(db.query_df("SELECT COUNT(*) AS n FROM transactions").iloc[0, 0])
    except Exception as exc:  # table not created yet: driver-specific error types
        raise MonitoringError(f"transactions is unavailable ({exc}); run `aml load` first") from exc
    if n == 0:
        raise MonitoringError("transactions is empty; run `aml load` first")


def _record(d: Detection) -> AlertRecord:
    return AlertRecord(
        rule_id=d.rule_id,
        rule_version=d.rule_version,
        subject_type="ACCOUNT",
        subject_id=d.account_id,
        accounts=((d.account_id, ROLE_SUBJECT),),
        window_start=d.window_start,
        window_end=d.window_end,
        txn_ids=d.txn_ids,
        amount_vnd=d.amount_vnd,
        reason=d.reason,
        details=dict(d.metrics),
        alert_key=d.alert_key,
    )


def run_monitoring(db: Database, settings: Settings, *, as_of: date | None = None) -> MonitoringRun:
    """Run all rules as of a date and store the result as a new run."""
    as_of = as_of or settings.data.reference_date
    _check_data(db)  # raises before anything is written
    detections = detect(db, settings, as_of=as_of)
    alerts = [_record(d) for d in detections]
    rules = [RuleRun(r.rule_id, r.rule_version, rule_params(r.rule_id, settings)) for r in RULES]
    run_id = record_run(db, as_of=as_of, source=SOURCE_RULE, rules=rules, alerts=alerts)
    return MonitoringRun(
        run_id=run_id,
        as_of=as_of,
        alerts=len(alerts),
        evidence=sum(len(d.txn_ids) for d in detections),
        by_rule={r.rule_id: sum(d.rule_id == r.rule_id for d in detections) for r in RULES},
    )
