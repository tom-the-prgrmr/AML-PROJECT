"""Data quality reads of the API: the results of one run and the trend of every rule."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from aml.api.errors import ApiError
from aml.api.values import iso_date, iso_seconds, lower_columns, plain
from aml.common.db import Database

RESULT_COLUMNS = (
    "rule_id",
    "table_name",
    "dimension",
    "scope",
    "description",
    "max_fail_rate",
    "total_rows",
    "failed_rows",
    "fail_rate",
    "status",
)
TREND_COLUMNS = (
    "rule_id",
    "table_name",
    "dimension",
    "run_id",
    "run_ts",
    "failed_rows",
    "fail_rate",
    "status",
    "prev_failed_rows",
    "delta_failed_rows",
)


def _query(db: Database, name: str) -> pd.DataFrame:
    text = db.sql_file(f"api/{name}").read_text(encoding="utf-8")
    return lower_columns(db.query_df(text.strip().rstrip(";")))


def _whole(value: Any) -> int | None:
    number = plain(value)
    return None if number is None else int(number)


def _sample_ids(value: Any) -> list[Any]:
    raw = plain(value)
    if raw is None:
        return []
    return list(json.loads(raw)) if isinstance(raw, str) else list(raw)


def _result(row: pd.Series) -> dict[str, Any]:
    out = {name: plain(row[name]) for name in RESULT_COLUMNS}
    out["sample_ids"] = _sample_ids(row["sample_ids"])
    out["prev_failed_rows"] = _whole(row["prev_failed_rows"])
    out["delta_failed_rows"] = _whole(row["delta_failed_rows"])
    return out


def dq_results(db: Database, run_id: int | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The rules of one run (default: the latest) ordered by rule id, with a run summary."""
    df = _query(db, "dq_results.sql")
    meta: dict[str, Any] = {
        "run_id": None,
        "as_of": None,
        "run_ts": None,
        "rules": 0,
        "passed": 0,
        "failed": 0,
        "no_data": 0,
    }
    if df.empty and run_id is None:
        return [], meta
    chosen = int(df["run_id"].max()) if run_id is None else run_id
    df = df[df["run_id"] == chosen]
    if df.empty:
        raise ApiError(404, "not_found", f"unknown dq run {chosen}")
    df = df.sort_values("rule_id", kind="stable")
    first = df.iloc[0]
    status = df["status"]
    meta.update(
        run_id=chosen,
        as_of=iso_date(first["as_of"]),
        run_ts=iso_seconds(first["run_ts"]),
        rules=len(df),
        passed=int((status == "PASS").sum()),
        failed=int((status == "FAIL").sum()),
        no_data=int((status == "NO_DATA").sum()),
    )
    return [_result(row) for _, row in df.iterrows()], meta


def _trend_row(row: pd.Series) -> dict[str, Any]:
    out = {name: plain(row[name]) for name in TREND_COLUMNS}
    out["run_id"] = int(row["run_id"])
    out["run_ts"] = iso_seconds(row["run_ts"])
    out["prev_failed_rows"] = _whole(row["prev_failed_rows"])
    out["delta_failed_rows"] = _whole(row["delta_failed_rows"])
    return out


def dq_trend(
    db: Database, *, rule_id: str | None, runs: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The latest ``runs`` runs of the trend view, ordered by (rule_id, run_id)."""
    df = _query(db, "dq_trend.sql")
    if rule_id is not None:
        df = df[df["rule_id"] == rule_id]
    run_ids = sorted({int(r) for r in df["run_id"]})[-runs:]
    df = df[df["run_id"].isin(run_ids)].sort_values(["rule_id", "run_id"], kind="stable")
    meta = {"runs": run_ids, "rules": int(df["rule_id"].nunique())}
    return [_trend_row(row) for _, row in df.iterrows()], meta
