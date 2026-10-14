"""Priority scores of the whole queue in one read (Phase 9c)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from aml.api.reads.cases import latest_run
from aml.api.values import lower_columns, plain
from aml.common.db import Database


def _floats(value: Any) -> Any:
    """Recursively turn Decimal (Oracle JSON numbers) into int or float."""
    if isinstance(value, dict):
        return {k: _floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_floats(v) for v in value]
    return plain(value) if isinstance(value, Decimal) else value


def _row(r: Any) -> dict[str, Any]:
    rank = plain(r["queue_rank"])
    top = r["top_features"]
    return {
        "case_id": str(r["case_id"]),
        "score": float(r["score"]),
        "queue_rank": None if rank is None else int(rank),
        "model_version": str(r["model_version"]),
        "top_features": _floats(json.loads(top) if isinstance(top, str) else top),
    }


def case_scores(db: Database) -> dict[str, Any]:
    """``{run_id, score_run_id, model_version, queue, scores}``; ranked rows first."""
    run = latest_run(db)
    text = db.sql_file("api/case_scores.sql").read_text(encoding="utf-8")
    df = lower_columns(db.query_df(text))
    scores = [_row(r) for _, r in df.iterrows()]
    scores.sort(key=lambda s: (s["queue_rank"] is None, s["queue_rank"] or 0, s["case_id"]))
    score_run_id = None if df.empty else plain(df.iloc[0]["score_run_id"])
    return {
        "run_id": None if run is None else run["run_id"],
        "score_run_id": None if score_run_id is None else int(score_run_id),
        "model_version": scores[0]["model_version"] if scores else None,
        "queue": sum(1 for s in scores if s["queue_rank"] is not None),
        "scores": scores,
    }
