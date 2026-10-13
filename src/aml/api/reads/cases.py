"""Case reads of the API: the queue, the latest run and the subjects of one case.

Everything returned is plain JSON data (no numpy scalars, no Timestamps, no NaN).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from aml.api.errors import ApiError
from aml.cases.runner import CaseError
from aml.cases.values import iso_date, lower_columns, plain
from aml.cases.view import load_case
from aml.common.db import Database

COUNTS = ("alerts", "rule_alerts", "network_alerts", "screening_alerts")
TIMES = ("window_start", "first_alert_ts", "last_alert_ts")


def _iso_seconds(value: Any) -> str | None:
    number = plain(value)
    return None if number is None else pd.Timestamp(number).strftime("%Y-%m-%dT%H:%M:%S")


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
        **{name: _iso_seconds(row[name]) for name in TIMES},
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
