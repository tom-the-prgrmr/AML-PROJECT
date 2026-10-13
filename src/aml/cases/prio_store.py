"""Reads and writes of the prioritization tables: `case_models` and `case_scores`.

Kept apart from `prioritize.py` so that module reads as the story (train, score, explain). Rows are
only ever inserted; a model is stored whole (artifact, parameters, metrics), never as a file.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from aml.cases.features import FEATURE_VERSION
from aml.cases.model import PrioritizationError, TrainedModel
from aml.cases.values import floats, lower_columns, plain_date
from aml.common.db import Database

NO_MODEL = "no model: run `aml cases train` first"
NO_RUN = "no case run yet: run `aml cases build` first"


def scalar(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def _text(value: Any) -> str:
    """A CLOB column as text (DuckDB returns str, Oracle a LOB)."""
    return str(value.read()) if hasattr(value, "read") else str(value)


def _json(value: Any) -> Any:
    """A JSON column: DuckDB gives text, Oracle may give text or the parsed value."""
    parsed = json.loads(_text(value)) if isinstance(value, str) or hasattr(value, "read") else value
    return floats(parsed)


def latest_run(db: Database) -> tuple[int, date]:
    """The newest case run and its as-of date."""
    df = lower_columns(db.query_df("SELECT run_id, as_of FROM case_runs ORDER BY run_id DESC"))
    if df.empty:
        raise PrioritizationError(NO_RUN)
    return int(df["run_id"].iloc[0]), plain_date(df["as_of"].iloc[0])


def latest_dispositions(db: Database) -> pd.DataFrame:
    """Newest decision of every case: ``case_id``, ``disposition``, ``run_id`` (its snapshot)."""
    df = lower_columns(
        db.query_df("SELECT case_id, disposition, run_id FROM case_dispositions_current")
    )
    df = df.astype({"case_id": str, "disposition": str, "run_id": int})
    return df.sort_values("case_id").reset_index(drop=True)


def insert_model(
    db: Database,
    *,
    kind: str,
    seed: int,
    as_of: date,
    counts: tuple[int, int, int],
    model: TrainedModel,
    actor: str,
) -> tuple[int, str]:
    """Store a trained model under the next ``model_id``; return the id and its version."""
    model_id = 1 + scalar(db, "SELECT COALESCE(MAX(model_id), 0) FROM case_models")
    version = f"prio/{kind}/{model_id}"
    cases, suspicious, false_positive = counts
    row = {
        "model_id": model_id,
        "kind": kind,
        "version": version,
        "feature_version": FEATURE_VERSION,
        "trained_ts": datetime.now(UTC).replace(tzinfo=None),
        "as_of": as_of,
        "seed": seed,
        "cases": cases,
        "suspicious": suspicious,
        "false_positive": false_positive,
        "features": json.dumps(list(model.features)),
        "params": json.dumps(model.params),
        "metrics": json.dumps(model.metrics),
        "artifact": model.artifact,
        "data_hash": model.data_hash,
        "actor": actor,
    }
    db.insert_df("case_models", pd.DataFrame([row]))
    return model_id, version


def read_model(db: Database, model_id: int | None) -> tuple[int, str, TrainedModel]:
    """A stored model by id, or the active (newest) one; it raises when there is none."""
    table = "case_model_active" if model_id is None else "case_models"
    where = "" if model_id is None else f" WHERE model_id = {int(model_id)}"
    df = lower_columns(db.query_df(f"SELECT * FROM {table}{where}"))
    if df.empty:
        raise PrioritizationError(NO_MODEL if model_id is None else f"unknown model_id {model_id}")
    r = df.iloc[0]
    model = TrainedModel(
        kind=str(r["kind"]),
        features=tuple(_json(r["features"])),
        artifact=_text(r["artifact"]),
        params=_json(r["params"]),
        metrics=_json(r["metrics"]),
        data_hash=str(r["data_hash"]),
        feature_version=str(r["feature_version"]),
    )
    return int(r["model_id"]), str(r["version"]), model


def insert_scores(
    db: Database,
    *,
    score_run_id: int,
    run_id: int,
    model_id: int,
    version: str,
    rows: list[dict[str, Any]],
) -> None:
    """Store one scoring run in a single insert; ``queue_rank`` is None for a CLOSED case."""
    scored_ts = datetime.now(UTC).replace(tzinfo=None)
    frame = pd.DataFrame(
        [
            {
                "score_run_id": score_run_id,
                "run_id": run_id,
                "case_id": r["case_id"],
                "model_id": model_id,
                "model_version": version,
                "score": r["score"],
                "queue_rank": r["queue_rank"],
                "top_features": json.dumps(r["top_features"]),
                "scored_ts": scored_ts,
            }
            for r in rows
        ]
    )
    # Rebuilt as an object column: a column with None would otherwise become float with NaN.
    frame["queue_rank"] = pd.Series([r["queue_rank"] for r in rows], dtype=object)
    db.insert_df("case_scores", frame)
