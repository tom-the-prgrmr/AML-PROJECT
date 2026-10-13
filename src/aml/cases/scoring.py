"""The parts of a scoring run that are not I/O on the model: top factors, queue rank, the
held-out measurement and the audit event of one case.

Kept apart from `prioritize.py` so that module reads as two steps, train and score.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from aml.cases.dispositions import SUSPICIOUS
from aml.cases.labels import has_ground_truth, truth_labels
from aml.cases.model import ranking_metrics
from aml.cases.prio_store import latest_dispositions
from aml.cases.runner import CLOSED
from aml.common.audit import AuditEvent
from aml.common.config import Settings
from aml.common.db import Database


def top_features(
    contributions: dict[str, float], values: pd.Series, n: int
) -> list[dict[str, Any]]:
    """The ``n`` features with the largest |contribution|; a tie goes to the smaller name."""
    rounded = {name: round(float(c), 4) for name, c in contributions.items()}
    names = sorted(rounded, key=lambda name: (-abs(rounded[name]), name))[:n]
    return [{"feature": f, "value": float(values[f]), "contribution": rounded[f]} for f in names]


def queue_ranks(scores: dict[str, float], status: dict[str, str]) -> dict[str, int]:
    """Queue rank of the OPEN / REOPENED cases: score down, case id up (done in Python)."""
    queue = sorted((c for c in scores if status[c] != CLOSED), key=lambda c: (-scores[c], c))
    return {case_id: i for i, case_id in enumerate(queue, start=1)}


def holdout(
    db: Database, settings: Settings, run_id: int, scores: dict[str, float]
) -> dict[str, Any]:
    """Queue metrics against the ground truth, which is only used to measure, never to decide.

    A queued case that already has a disposition (a REOPENED one) was in the training set, so it is
    left out; ``excluded_trained`` says how many.
    """
    if not scores or not has_ground_truth(db):
        return {}
    trained = set(latest_dispositions(db)["case_id"])
    fresh = {c: s for c, s in scores.items() if c not in trained}
    if not fresh:
        return {"n": 0, "excluded_trained": len(scores)}
    truth = truth_labels(db, run_id)
    y = pd.Series({c: int(truth[c].disposition == SUSPICIOUS) for c in fresh}, dtype=int)
    metrics = ranking_metrics(
        y, pd.Series(fresh, dtype=float), settings.cases.prioritization.top_fractions
    )
    return metrics | {"excluded_trained": len(scores) - len(fresh)}


def case_event(
    row: dict[str, Any], queue: int, version: str, score_run_id: int, run_id: int, model_id: int
) -> AuditEvent:
    place = (
        "not in the queue (CLOSED)"
        if row["queue_rank"] is None
        else f"queue rank {row['queue_rank']} of {queue}"
    )
    factors = ", ".join(f"{t['feature']} {t['contribution']:+.2f}" for t in row["top_features"])
    return AuditEvent(
        module="cases",
        entity_type="case",
        entity_id=row["case_id"],
        decision="PRIORITIZED",
        reason=(
            f"priority score {row['score']:.4f} from {version}, {place}; top factors: {factors}; "
            "ranking only, no disposition"
        ),
        version=version,
        details={
            "score_run_id": score_run_id, "run_id": run_id, "model_id": model_id,
            "score": row["score"], "queue_rank": row["queue_rank"],
            "top_features": row["top_features"],
        },
    )  # fmt: skip
