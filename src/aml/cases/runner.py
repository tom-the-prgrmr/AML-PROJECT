"""Case run: collect alert items, group them into cases, store a full snapshot, audit the changes.

`run_cases` rewrites everything under a new ``run_id`` (like `run_er`); nothing is UPDATEd. The
``*_current`` views follow ``MAX(run_id)`` of ``case_runs``, so that row is written last. The
system only groups and enriches: a case becomes CLOSED solely through a human disposition
(`aml.cases.dispositions`, which imports `CaseError` from here), never by this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

import pandas as pd

from aml.cases.consolidate import assign_cases
from aml.cases.enrich import enrich_cases
from aml.cases.items import collect_items
from aml.cases.suppression import count_by_rule, evaluate_suppression, suppression_events
from aml.common.audit import AuditEvent, audit_many
from aml.common.config import Settings
from aml.common.db import Database

__all__ = ["CASES_VERSION", "SECTIONS", "CaseError", "CaseRun", "run_cases"]

CASES_VERSION = "cases/v1"
OPEN, REOPENED, CLOSED = "OPEN", "REOPENED", "CLOSED"
ACTIVE, SUPPRESSED = "ACTIVE", "SUPPRESSED"
SECTIONS = ("kyc", "linked_cifs", "dq_issues", "txn_summary", "network", "history")

_SOURCES = ("RULE", "NETWORK", "SCREENING", "ANOMALY")
_ALERT_COLUMNS = [
    "run_id", "item_key", "golden_customer_id", "case_id", "source", "rule_id", "alert_ref", "cif",
    "entry_id", "event_ts", "end_ts", "amount_vnd", "txn_count", "status", "suppression_rule",
    "suppression_reason", "retriggered", "reason", "details",
]  # fmt: skip
_CASE_COLUMNS = [
    "run_id", "case_id", "golden_customer_id", "window_start", "first_alert_ts", "last_alert_ts",
    "alerts", "rule_alerts", "network_alerts", "screening_alerts", "sources", "status", "reason",
]  # fmt: skip


class CaseError(RuntimeError):
    """Cases cannot be built or read with the data they were given."""


@dataclass(frozen=True)
class CaseRun:
    run_id: int
    as_of: date
    items: int  # (alert, golden customer) rows before suppression
    alerts: int  # distinct item_key
    suppressed: int
    active: int
    cases: int
    opened: int  # cases whose case_id appears for the first time in any run
    reopened: int  # cases that became REOPENED in this run (were not REOPENED in the previous)
    closed: int  # cases that became CLOSED in this run (were not CLOSED in the previous)
    graph_source: str  # "gds" | "networkx" | "none"
    suppressed_by_rule: dict[str, int]  # GOOD_GUY and HIBERNATION, both present even with 0
    lifted: int  # items a good-guy row or a hibernation no longer covers (back to ACTIVE)


def _scalar(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def _check_inputs(db: Database) -> None:
    """Raise before the first write when the upstream phases have not run."""
    if _scalar(db, "SELECT COUNT(*) FROM customer_golden") == 0:
        raise CaseError("customer_golden is empty: run `aml er` first")
    sources = _scalar(db, "SELECT COUNT(*) FROM screening_runs") + _scalar(
        db, "SELECT COUNT(*) FROM monitoring_runs"
    )
    if sources == 0:
        raise CaseError("no alert source has run: run `aml screen` or `aml monitor` first")


def _next_run_id(db: Database) -> int:
    # cases and case_alerts count too: a run that failed before its case_runs row must not
    # reuse its id.
    tables = ("case_runs", "cases", "case_alerts")
    return 1 + max(_scalar(db, f"SELECT COALESCE(MAX(run_id), 0) FROM {t}") for t in tables)


def _config_hash(settings: Settings) -> str:
    cfg = settings.cases.model_dump(mode="json")
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _ts(value: pd.Timestamp) -> str:
    return f"{value:%Y-%m-%d %H:%M:%S}"


def _case_rows(run_id: int, active: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """One row per case (without ``status``), sorted by ``case_id``."""
    rows = []
    for case_id, g in active.groupby("case_id", sort=True):
        counts = {s: int((g["source"] == s).sum()) for s in _SOURCES}
        golden = str(g["golden_customer_id"].iloc[0])
        first, last = g["event_ts"].min(), g["end_ts"].max()
        anomaly = f", {counts['ANOMALY']} ANOMALY" if counts["ANOMALY"] else ""  # Phase 7b-i
        reason = (
            f"{len(g)} alert(s) ({counts['RULE']} RULE, {counts['NETWORK']} NETWORK, "
            f"{counts['SCREENING']} SCREENING{anomaly}) on {golden} between {_ts(first)} and "
            f"{_ts(last)}; window of {window_days} days from the first alert"
        )
        rows.append(
            {
                "run_id": run_id,
                "case_id": case_id,
                "golden_customer_id": golden,
                "window_start": g["window_start"].iloc[0],
                "first_alert_ts": first,
                "last_alert_ts": last,
                "alerts": len(g),
                "rule_alerts": counts["RULE"],
                "network_alerts": counts["NETWORK"],
                "screening_alerts": counts["SCREENING"],
                "sources": "+".join(sorted(set(g["source"]))),
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)


def _item_keys(db: Database, sql: str) -> dict[str, set[str]]:
    df = db.query_df(sql)
    df.columns = [str(c).lower() for c in df.columns]
    keys: dict[str, set[str]] = {}
    for case_id, item_key in zip(df["case_id"], df["item_key"], strict=True):
        keys.setdefault(str(case_id), set()).add(str(item_key))
    return keys


def _statuses(db: Database, active: pd.DataFrame, case_ids: list[str]) -> dict[str, str]:
    """OPEN without a disposition; CLOSED when nothing new came since the latest one; else REOPENED.

    "Nothing new" = every ACTIVE item of the case is in the case's snapshot of the run the latest
    disposition refers to, and none is ``retriggered``.
    """
    decided = db.query_df("SELECT case_id FROM case_dispositions_current")
    decided_ids = {str(c) for c in decided["case_id"]}
    seen = _item_keys(
        db,
        "SELECT a.case_id, a.item_key FROM case_dispositions_current d "
        "JOIN case_alerts a ON a.run_id = d.run_id AND a.case_id = d.case_id",
    )
    keys = {c: set(g["item_key"]) for c, g in active.groupby("case_id")}
    retriggered = {c for c, g in active.groupby("case_id") if (g["retriggered"] == 1).any()}
    status = {}
    for case_id in case_ids:
        if case_id not in decided_ids:
            status[case_id] = OPEN
        elif keys[case_id] <= seen.get(case_id, set()) and case_id not in retriggered:
            status[case_id] = CLOSED
        else:
            status[case_id] = REOPENED
    return status


def _events(
    run_id: int,
    cases: pd.DataFrame,
    active: pd.DataFrame,
    previous_status: dict[str, str],
    previous_keys: dict[str, set[str]],
    ever_seen: set[str],
) -> list[AuditEvent]:
    """CASE_OPENED / CASE_REOPENED / CASE_UPDATED for new or changed cases; none for unchanged."""
    keys = {c: sorted(g["item_key"]) for c, g in active.groupby("case_id")}
    events = []
    for row in cases.itertuples():
        case_id = str(row.case_id)
        if case_id not in ever_seen:
            decision = "CASE_OPENED"
        elif row.status == REOPENED and previous_status.get(case_id) != REOPENED:
            decision = "CASE_REOPENED"
        elif set(keys[case_id]) != previous_keys.get(case_id, set()):
            decision = "CASE_UPDATED"
        else:
            continue
        events.append(
            AuditEvent(
                module="cases",
                entity_type="case",
                entity_id=case_id,
                decision=decision,
                reason=row.reason,
                version=CASES_VERSION,
                details={
                    "run_id": run_id,
                    "golden_customer_id": row.golden_customer_id,
                    "alerts": int(row.alerts),
                    "sources": row.sources,
                    "item_keys": keys[case_id],
                },
            )
        )
    return events


def _run_event(run: CaseRun) -> AuditEvent:
    return AuditEvent(
        module="cases",
        entity_type="case_run",
        entity_id=str(run.run_id),
        decision="CASE_RUN_COMPLETED",
        reason=(
            f"Built {run.cases} case(s) from {run.items} item(s) ({run.alerts} alert(s)) as of "
            f"{run.as_of.isoformat()}: {run.opened} opened, {run.reopened} reopened, "
            f"{run.closed} closed"
        ),
        version=CASES_VERSION,
        details=asdict(run) | {"as_of": run.as_of.isoformat()},
    )


def run_cases(
    db: Database, settings: Settings, *, as_of: date | None = None, actor: str | None = None
) -> CaseRun:
    """Build the cases as of a date and store them as a new run; return its summary."""
    as_of = as_of or settings.data.reference_date
    _check_inputs(db)  # raises before anything is written
    items = collect_items(db, settings, as_of=as_of)
    # Suppressed items are stored but belong to no case and do not anchor a window.
    items = evaluate_suppression(db, settings, items, as_of=as_of)
    active = assign_cases(items[items["status"] == ACTIVE], settings.cases.window_days)

    run_id = _next_run_id(db)
    cases = _case_rows(run_id, active, settings.cases.window_days)
    status = _statuses(db, active, list(cases["case_id"]) if not cases.empty else [])
    if not cases.empty:
        cases["status"] = cases["case_id"].map(status)

    # State of the previous run, for the audit events and the opened / reopened / closed counts.
    previous_run = _scalar(db, "SELECT COALESCE(MAX(run_id), 0) FROM case_runs")
    prev_df = db.query_df(f"SELECT case_id, status FROM cases WHERE run_id = {previous_run}")
    previous_status = dict(zip(prev_df["case_id"].astype(str), prev_df["status"], strict=True))
    previous_keys = _item_keys(
        db,
        f"SELECT case_id, item_key FROM case_alerts WHERE run_id = {previous_run} "
        f"AND status = '{ACTIVE}'",  # a SUPPRESSED item has no case_id
    )
    # Published runs only: rows of a run that died before its `case_runs` row do not count.
    ever_seen = {
        str(c)
        for c in db.query_df(
            "SELECT DISTINCT case_id FROM cases WHERE run_id IN (SELECT run_id FROM case_runs)"
        )["case_id"]
    }

    # Every item is stored, before enrichment: `history.suppressed_items` reads this run's rows.
    if not items.empty:
        suppressed = items[items["status"] == SUPPRESSED].assign(case_id=None)
        parts = [f for f in (active, suppressed) if not f.empty]  # no empty frames in concat
        written = pd.concat(parts).assign(run_id=run_id)
        written["details"] = written["details"].astype(object)
        db.insert_df("case_alerts", written[_ALERT_COLUMNS])
    if not cases.empty:
        db.insert_df("cases", cases[_CASE_COLUMNS])
    # Enrichment runs after `cases` and before `case_runs`, the row that makes the run current.
    graph_source = enrich_cases(
        db, settings, run_id=run_id, as_of=as_of, cases=cases, active=active
    )

    now_status = {} if cases.empty else dict(zip(cases["case_id"], cases["status"], strict=True))
    run = CaseRun(
        run_id=run_id,
        as_of=as_of,
        items=len(items),
        alerts=int(items["item_key"].nunique()),
        suppressed=int((items["status"] == SUPPRESSED).sum()),
        active=len(active),
        cases=len(cases),
        opened=sum(c not in ever_seen for c in now_status),
        reopened=sum(
            s == REOPENED and previous_status.get(c) != REOPENED for c, s in now_status.items()
        ),
        closed=sum(s == CLOSED and previous_status.get(c) != CLOSED for c, s in now_status.items()),
        graph_source=graph_source,
        suppressed_by_rule=count_by_rule(items),
        lifted=int(items["lifted"].sum()),
    )
    db.insert_df(
        "case_runs",
        pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "run_ts": datetime.now(UTC).replace(tzinfo=None),
                    "as_of": as_of,
                    "window_days": settings.cases.window_days,
                    "items": run.items,
                    "alerts": run.alerts,
                    "suppressed": run.suppressed,
                    "active": run.active,
                    "cases": run.cases,
                    "opened": run.opened,
                    "reopened": run.reopened,
                    "closed": run.closed,
                    "graph_source": graph_source,
                    "version": CASES_VERSION,
                    "config_hash": _config_hash(settings),
                }
            ]
        ),
    )
    events = suppression_events(run_id, items)
    if not cases.empty:
        events += _events(run_id, cases, active, previous_status, previous_keys, ever_seen)
    events.append(_run_event(run))
    if actor:
        events = [e.model_copy(update={"actor": actor}) for e in events]
    audit_many(db, events)
    return run
