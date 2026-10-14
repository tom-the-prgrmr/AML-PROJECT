"""Case reads of the API: the queue, the latest run and the subjects of one case.

Everything returned is plain JSON data (no numpy scalars, no Timestamps, no NaN).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from aml.api.errors import ApiError
from aml.api.values import in_filter, iso_date, iso_seconds, lower_columns, plain
from aml.cases.runner import CaseError
from aml.cases.view import load_case
from aml.common.db import Database
from aml.dba.masking import mask_name

COUNTS = ("alerts", "rule_alerts", "network_alerts", "screening_alerts")
TIMES = ("window_start", "first_alert_ts", "last_alert_ts")


def translate_case_error(exc: CaseError) -> Exception:
    """An unknown case id is the caller's 404; any other CaseError stays an internal error."""
    if str(exc).startswith("unknown case_id"):
        return ApiError(404, "not_found", str(exc))
    return exc


def latest_run(db: Database) -> dict[str, Any] | None:
    """``{run_id, as_of, cases}`` of the latest case run, or None before the first run."""
    df = lower_columns(
        db.query_df(
            "SELECT run_id, as_of, cases FROM case_runs "
            "WHERE run_id = (SELECT MAX(run_id) FROM case_runs)"
        )
    )
    if df.empty:
        return None
    row = df.iloc[0]
    return {
        "run_id": int(row["run_id"]),
        "as_of": iso_date(row["as_of"]),
        "cases": int(row["cases"]),
    }


def _case(row: pd.Series) -> dict[str, Any]:
    decided = plain(row["disposition"])
    disposition = (
        None
        if decided is None
        else {
            "disposition": decided,
            "actor": plain(row["disposition_actor"]),
            "decided_on": iso_date(row["disposition_decided_on"]),
        }
    )
    return {
        "case_id": row["case_id"],
        "golden_customer_id": row["golden_customer_id"],
        "status": row["status"],
        **{name: int(row[name]) for name in COUNTS},
        "sources": str(row["sources"]).split("+"),
        **{name: iso_seconds(row[name]) for name in TIMES},
        "reason": row["reason"],
        "disposition": disposition,
    }


def list_cases(
    db: Database, *, status: str | None, limit: int, offset: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The queue of the latest run, newest alert first; returns ``(rows, meta)``."""
    run = latest_run(db)
    meta: dict[str, Any] = {
        "run_id": run["run_id"] if run else None,
        "as_of": run["as_of"] if run else None,
        "total": 0,
        "limit": limit,
        "offset": offset,
    }
    if run is None:
        return [], meta
    text = db.sql_file("api/case_list.sql").read_text(encoding="utf-8")
    df = lower_columns(db.query_df(text.strip().rstrip(";")))
    if status is not None:
        df = df[df["status"] == status]
    df = df.sort_values(["last_alert_ts", "case_id"], ascending=[False, True], kind="stable")
    meta["total"] = len(df)
    page = df.iloc[offset : offset + limit]
    return [_case(row) for _, row in page.iterrows()], meta


def _alert(alert: Any) -> dict[str, Any]:
    return {
        "item_key": alert.item_key,
        "source": alert.source,
        "rule_id": alert.rule_id,
        "alert_ref": alert.alert_ref,
        "cif": alert.cif,
        "event_ts": iso_seconds(alert.event_ts),
        "end_ts": iso_seconds(alert.end_ts),
        "amount_vnd": alert.amount_vnd,
        "reason": alert.reason,
    }


def case_detail(db: Database, case_id: str) -> dict[str, Any]:
    """One case without subjects and score; identical for every role (nothing here is PII)."""
    try:
        view = load_case(db, case_id, masked=True, scored=False)
    except CaseError as exc:
        raise translate_case_error(exc) from exc
    decision = view.disposition
    disposition = (
        None
        if decision is None
        else {
            "disposition_id": decision.disposition_id,
            "disposition": decision.disposition,
            "reason": decision.reason,
            "actor": decision.actor,
            "origin": decision.origin,
            "decided_on": iso_date(decision.decided_on),
            "run_id": decision.run_id,
        }
    )
    return {
        "case_id": view.case_id,
        "run_id": view.run_id,
        "golden_customer_id": view.golden_customer_id,
        "status": view.status,
        "window_start": iso_seconds(view.window_start),
        "first_alert_ts": iso_seconds(view.first_alert_ts),
        "last_alert_ts": iso_seconds(view.last_alert_ts),
        "reason": view.reason,
        "alerts": [_alert(a) for a in view.alerts],
        "enrichment": view.enrichment,
        "disposition": disposition,
    }


def case_transactions(
    db: Database, case_id: str, *, masked: bool, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    """Transactions behind the case's alerts, one row per transaction; returns ``(page, total)``."""
    try:
        load_case(db, case_id, masked=True, scored=False)
    except CaseError as exc:
        raise translate_case_error(exc) from exc
    text = db.sql_file("api/case_transactions.sql").read_text(encoding="utf-8")
    one_case = in_filter("ca.case_id", [case_id])  # only this case's evidence leaves the database
    df = lower_columns(db.query_df(f"{text.strip().rstrip(';')} AND {one_case}"))
    rows: list[dict[str, Any]] = []
    for txn_id, group in df.groupby("txn_id", sort=False):
        first = group.iloc[0]
        name = plain(first["counterparty_name"])
        rows.append(
            {
                "txn_id": txn_id,
                "txn_ts": iso_seconds(first["txn_ts"]),
                "from_account_id": plain(first["from_account_id"]),
                "to_account_id": plain(first["to_account_id"]),
                "amount_vnd": plain(first["amount_vnd"]),
                "channel": plain(first["channel"]),
                "memo": plain(first["memo"]),
                "counterparty_name": mask_name(name) if masked else name,
                "item_keys": sorted(set(group["item_key"])),
            }
        )
    rows.sort(key=lambda r: (r["txn_ts"], r["txn_id"]))
    return rows[offset : offset + limit], len(rows)


def _plain_subject(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        value = plain(value)
        if isinstance(value, datetime | date):  # dob arrives as a Timestamp
            value = pd.Timestamp(value).date().isoformat()
        out[key] = value
    return out


def case_subjects(db: Database, case_id: str, *, masked: bool) -> list[dict[str, Any]]:
    """Customer rows of a case: ``customers_masked`` when ``masked``, else ``customers``."""
    try:
        view = load_case(db, case_id, masked=masked, scored=False)
    except CaseError as exc:
        raise translate_case_error(exc) from exc
    return [_plain_subject(dict(s)) for s in view.subjects]
