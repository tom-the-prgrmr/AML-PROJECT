"""Store monitoring runs and alerts: ids, the four tables, audit events.

This is the single write path for alerts; Phase 5c reuses it for network alerts.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pandas as pd

from aml.common.audit import AuditEvent, audit_many
from aml.common.db import Database

_ACCOUNT_CHUNK = 500  # keeps IN lists far below Oracle's 1000-element limit


@dataclass(frozen=True)
class RuleRun:
    rule_id: str
    rule_version: str
    params: dict[str, int | float | str]


@dataclass(frozen=True)
class AlertRecord:
    rule_id: str
    rule_version: str
    subject_type: str  # "ACCOUNT" | "ACCOUNT_GROUP"
    subject_id: str
    accounts: tuple[tuple[str, str], ...]  # (account_id, role)
    window_start: datetime
    window_end: datetime
    txn_ids: tuple[str, ...]
    amount_vnd: int
    reason: str
    details: dict[str, object]
    alert_key: str


def _scalar(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def next_run_id(db: Database) -> int:
    # alerts counts too: a run that failed before its monitoring_runs rows must not reuse its id.
    return 1 + max(
        _scalar(db, "SELECT COALESCE(MAX(run_id), 0) FROM monitoring_runs"),
        _scalar(db, "SELECT COALESCE(MAX(run_id), 0) FROM alerts"),
    )


def _cif_lookup(db: Database, account_ids: Sequence[str]) -> dict[str, str | None]:
    wanted = sorted(set(account_ids))
    found: dict[str, str | None] = {}
    for i in range(0, len(wanted), _ACCOUNT_CHUNK):
        quoted = ", ".join("'" + a.replace("'", "''") + "'" for a in wanted[i : i + _ACCOUNT_CHUNK])
        df = db.query_df(f"SELECT account_id, cif FROM accounts WHERE account_id IN ({quoted})")
        df.columns = [str(c).lower() for c in df.columns]
        found.update(zip(df["account_id"], df["cif"], strict=True))
    return {a: found.get(a) for a in wanted}


def _alert_rows(
    run_id: int, first_alert_id: int, source: str, alerts: Sequence[AlertRecord]
) -> pd.DataFrame:
    rows = [
        {
            "alert_id": first_alert_id + i,
            "run_id": run_id,
            "alert_key": a.alert_key,
            "source": source,
            "rule_id": a.rule_id,
            "rule_version": a.rule_version,
            "subject_type": a.subject_type,
            "subject_id": a.subject_id,
            "window_start": a.window_start,
            "window_end": a.window_end,
            "txn_count": len(a.txn_ids),
            "amount_vnd": int(a.amount_vnd),
            "reason": a.reason,
            "details": json.dumps(a.details, ensure_ascii=False),
        }
        for i, a in enumerate(alerts)
    ]
    return pd.DataFrame(rows)


def _account_rows(
    first_alert_id: int, alerts: Sequence[AlertRecord], cifs: dict[str, str | None]
) -> pd.DataFrame:
    rows = [
        {"alert_id": first_alert_id + i, "account_id": account, "cif": cifs[account], "role": role}
        for i, a in enumerate(alerts)
        for account, role in a.accounts
    ]
    return pd.DataFrame(rows, columns=["alert_id", "account_id", "cif", "role"])


def _evidence_rows(first_alert_id: int, alerts: Sequence[AlertRecord]) -> pd.DataFrame:
    rows = [
        {"alert_id": first_alert_id + i, "txn_id": txn_id}
        for i, a in enumerate(alerts)
        for txn_id in a.txn_ids
    ]
    return pd.DataFrame(rows, columns=["alert_id", "txn_id"])


def _run_rows(
    run_id: int,
    as_of: date,
    source: str,
    rules: Sequence[RuleRun],
    alerts: Sequence[AlertRecord],
) -> pd.DataFrame:
    run_ts = datetime.now(UTC).replace(tzinfo=None)
    rows = [
        {
            "run_id": run_id,
            "rule_id": r.rule_id,
            "run_ts": run_ts,
            "as_of": as_of,
            "source": source,
            "rule_version": r.rule_version,
            "params": json.dumps(r.params, ensure_ascii=False),
            "alerts": sum(a.rule_id == r.rule_id for a in alerts),
            "evidence": sum(len(a.txn_ids) for a in alerts if a.rule_id == r.rule_id),
        }
        for r in rules
    ]
    return pd.DataFrame(rows)


def _events(
    run_id: int,
    first_alert_id: int,
    as_of: date,
    source: str,
    rules: Sequence[RuleRun],
    alerts: Sequence[AlertRecord],
) -> list[AuditEvent]:
    events = [
        AuditEvent(
            module="monitoring",
            entity_type="alert",
            entity_id=str(first_alert_id + i),
            decision="ALERT",
            reason=a.reason,
            version=f"{a.rule_id}/{a.rule_version}",
            details={
                "run_id": run_id,
                "alert_key": a.alert_key,
                "rule_id": a.rule_id,
                "subject_id": a.subject_id,
                "txn_count": len(a.txn_ids),
                "amount_vnd": int(a.amount_vnd),
            },
        )
        for i, a in enumerate(alerts)
    ]
    by_rule = {r.rule_id: sum(a.rule_id == r.rule_id for a in alerts) for r in rules}
    evidence = sum(len(a.txn_ids) for a in alerts)
    events.append(
        AuditEvent(
            module="monitoring",
            entity_type="monitoring_run",
            entity_id=str(run_id),
            decision="MONITORING_RUN_COMPLETED",
            reason=(
                f"Ran {len(rules)} {source} rule(s) as of {as_of.isoformat()}: "
                f"{len(alerts)} alert(s) with {evidence} evidence transaction row(s)."
            ),
            version=f"monitoring/{source.lower()}",
            details={
                "as_of": as_of.isoformat(),
                "source": source,
                "alerts": len(alerts),
                "evidence": evidence,
                "by_rule": by_rule,
            },
        )
    )
    return events


def record_run(
    db: Database,
    *,
    as_of: date,
    source: str,
    rules: Sequence[RuleRun],
    alerts: Sequence[AlertRecord],
) -> int:
    """Store one run (allocating run_id and alert_ids); return the run_id."""
    unknown = {a.rule_id for a in alerts} - {r.rule_id for r in rules}
    if unknown:  # alerts_current joins on monitoring_runs.rule_id and would never show them
        raise ValueError(f"alerts for rules missing from `rules`: {sorted(unknown)}")
    run_id = next_run_id(db)
    first_alert_id = 1 + _scalar(db, "SELECT COALESCE(MAX(alert_id), 0) FROM alerts")
    cifs = _cif_lookup(db, [account for a in alerts for account, _ in a.accounts])

    # monitoring_runs goes last: alerts_current follows MAX(run_id) there, so it switches to the
    # new run only once its alerts, accounts and evidence are all stored.
    if alerts:
        db.insert_df("alerts", _alert_rows(run_id, first_alert_id, source, alerts))
        accounts = _account_rows(first_alert_id, alerts, cifs)
        if not accounts.empty:
            db.insert_df("alert_accounts", accounts)
        evidence = _evidence_rows(first_alert_id, alerts)
        if not evidence.empty:
            db.insert_df("alert_evidence", evidence)
    db.insert_df("monitoring_runs", _run_rows(run_id, as_of, source, rules, alerts))
    audit_many(db, _events(run_id, first_alert_id, as_of, source, rules, alerts))
    return run_id
