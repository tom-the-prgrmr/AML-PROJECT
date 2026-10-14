"""Anomaly features of a case: the highest score and the number of alerted customer-months.

They count the customer-months of the CIFs linked to the case whose calendar month overlaps the
case's stored transaction window, in the current anomaly run. Like the memo columns of Phase 8d
they live in their own table (`case_anomaly_features`), so the Phase 7c feature set and its stored
snapshots stay as they are. `NON_NEGATIVE_ANOMALY` goes to `fit_guarded`, so a fitted model can
never lower a case's score because the anomaly model found its customer more unusual.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pandas as pd

from aml.cases.values import lower_columns
from aml.common.config import Settings
from aml.common.db import Database

ANOMALY_CASE_FEATURES = ("anomaly_max_score", "anomaly_flagged_months")
NON_NEGATIVE_ANOMALY = ANOMALY_CASE_FEATURES
ANOMALY_FEATURE_TAG = "+anom/v1"

Window = tuple[list[str], date, date]  # CIFs of the case, first and last day of its transactions


def _scalar(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def anomaly_schema_ready(db: Database) -> bool:
    """True when the DDL 200 tables exist; any other database error is not swallowed."""
    if db.backend == "oracle":
        sql = (
            "SELECT COUNT(*) FROM user_tables "
            "WHERE table_name IN ('ANOMALY_RUNS', 'ANOMALY_SCORES', 'CASE_ANOMALY_FEATURES')"
        )
    else:
        sql = (
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name IN ('anomaly_runs', 'anomaly_scores', 'case_anomaly_features')"
        )
    return _scalar(db, sql) == 3


def current_anomaly_run(db: Database) -> tuple[int, str] | None:
    """``(run_id, model_version)`` of the newest anomaly run, or None before the first."""
    if not anomaly_schema_ready(db):  # a database built before Phase 7b-i: no run, no columns
        return None
    df = lower_columns(
        db.query_df(
            "SELECT run_id, model_version FROM anomaly_runs "
            "WHERE run_id = (SELECT MAX(run_id) FROM anomaly_runs)"
        )
    )
    return None if df.empty else (int(df["run_id"].iloc[0]), str(df["model_version"].iloc[0]))


def anomaly_info(db: Database, dropped: tuple[str, ...]) -> dict[str, Any]:
    """What a model that uses the anomaly columns records about the run it was trained with."""
    current = current_anomaly_run(db)
    run_id, model_version = current if current else (None, None)
    return {"run_id": run_id, "model_version": model_version, "dropped_features": list(dropped)}


def _content(value: Any) -> dict[str, Any]:
    """A JSON column as a dict (DuckDB returns text, Oracle text, a LOB or the parsed value)."""
    if hasattr(value, "read"):
        value = value.read()
    return dict(json.loads(value)) if isinstance(value, str) else dict(value)


def _windows(db: Database, run_id: int) -> dict[str, Window | None]:
    """Every case of a run with its linked CIFs and the transaction window its snapshot stored."""
    cases = lower_columns(db.query_df(f"SELECT case_id FROM cases WHERE run_id = {run_id}"))
    blocks = lower_columns(
        db.query_df(
            "SELECT case_id, section, content FROM case_enrichment "
            f"WHERE run_id = {run_id} AND section IN ('txn_summary', 'linked_cifs')"
        )
    )
    stored: dict[str, dict[str, dict[str, Any]]] = {}
    for case_id, section, content in zip(
        blocks["case_id"], blocks["section"], blocks["content"], strict=True
    ):
        stored.setdefault(str(case_id), {})[str(section)] = _content(content)
    out: dict[str, Window | None] = {}
    for case_id in sorted(str(c) for c in cases["case_id"]):
        txn = stored.get(case_id, {}).get("txn_summary", {})
        cifs = [str(c) for c in stored.get(case_id, {}).get("linked_cifs", {}).get("cifs") or []]
        if cifs and txn.get("window_start") and txn.get("window_end"):
            start, end = (date.fromisoformat(txn[k]) for k in ("window_start", "window_end"))
            out[case_id] = (cifs, start, end)
        else:
            out[case_id] = None  # no stored window: no customer-month to match
    return out


def _samples(db: Database, anomaly_run_id: int) -> dict[str, pd.DataFrame]:
    """Customer-months of an anomaly run per CIF, with the first day of the month and the next."""
    df = lower_columns(
        db.query_df(
            f"SELECT cif, month, score, alerted FROM anomaly_scores WHERE run_id = {anomaly_run_id}"
        )
    )
    df["score"] = pd.to_numeric(df["score"]).astype("float64")
    df["alerted"] = pd.to_numeric(df["alerted"]).astype("int64")
    first = pd.to_datetime(df["month"] + "-01")
    df["month_start"], df["month_end"] = first, first + pd.offsets.MonthBegin(1)
    return {str(cif): g for cif, g in df.groupby("cif")}


def _case_values(samples: dict[str, pd.DataFrame], window: Window | None) -> tuple[float, float]:
    """(highest score, alerted months) of the customer-months that overlap the window."""
    if window is None:
        return 0.0, 0.0
    cifs, start, end = window
    parts = [samples[c] for c in cifs if c in samples]
    if not parts:
        return 0.0, 0.0
    both = pd.concat(parts)
    last_day = pd.Timestamp(end + timedelta(days=1))
    hit = both[(both["month_start"] < last_day) & (both["month_end"] > pd.Timestamp(start))]
    if hit.empty:
        return 0.0, 0.0
    return float(hit["score"].max()), float(hit["alerted"].sum())


def write_anomaly_features(db: Database, settings: Settings, run_id: int) -> int:
    """Store the two features of every case of a case run; return the number of rows written.

    0 before the first anomaly run, and when the run already has rows for the current anomaly run.
    """
    del settings  # part of the interface shared with the memo features
    current = current_anomaly_run(db)
    if current is None:
        return 0
    anomaly_run_id = current[0]
    stored = _scalar(
        db,
        "SELECT COUNT(*) FROM case_anomaly_features "
        f"WHERE run_id = {run_id} AND anomaly_run_id = {anomaly_run_id}",
    )
    if stored:
        return 0
    samples = _samples(db, anomaly_run_id)
    rows = []
    for case_id, window in _windows(db, run_id).items():
        values = _case_values(samples, window)
        rows += [
            {
                "run_id": run_id,
                "case_id": case_id,
                "anomaly_run_id": anomaly_run_id,
                "feature": name,
                "value": value,
            }
            for name, value in zip(ANOMALY_CASE_FEATURES, values, strict=True)
        ]
    return db.insert_df("case_anomaly_features", pd.DataFrame(rows)) if rows else 0


def read_anomaly_features(db: Database, settings: Settings, run_id: int) -> pd.DataFrame | None:
    """Stored features of a case run for the current anomaly run: index ``case_id`` ascending,
    columns in `ANOMALY_CASE_FEATURES` order. None before any anomaly run or before they are
    written."""
    del settings
    current = current_anomaly_run(db)
    if current is None:
        return None
    df = lower_columns(
        db.query_df(
            "SELECT case_id, feature, value FROM case_anomaly_features "
            f"WHERE run_id = {run_id} AND anomaly_run_id = {current[0]}"
        )
    )
    if df.empty:
        return None
    wide = df.pivot(index="case_id", columns="feature", values="value").astype(float)
    wide = wide.reindex(columns=list(ANOMALY_CASE_FEATURES))
    wide.columns.name = None
    return wide.loc[sorted(wide.index)].rename_axis("case_id")


def ensure_anomaly_features(db: Database, settings: Settings, run_id: int) -> pd.DataFrame | None:
    """Anomaly features of a case run, computed now if this is the first time they are needed."""
    write_anomaly_features(db, settings, run_id)
    return read_anomaly_features(db, settings, run_id)


def decided_anomaly_features(
    db: Database, settings: Settings, decided: pd.DataFrame
) -> pd.DataFrame | None:
    """Anomaly columns of the decided cases, each from the snapshot its decision saw.

    None when there is no anomaly run: training then does not use the columns.
    """
    if current_anomaly_run(db) is None:
        return None
    frames = []
    for run_id, part in decided.groupby("run_id"):
        frame = ensure_anomaly_features(db, settings, int(run_id))
        if frame is None:
            return None
        frames.append(frame.loc[list(part["case_id"])])
    return pd.concat(frames).sort_index() if frames else None
