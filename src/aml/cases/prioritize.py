"""Train and apply the case-ranking model, and audit every step.

`train` learns from the cases a person (or the simulation) has decided, on the feature snapshot the
decision saw. `score` ranks every current case and stores the score with its top factors. Both only
write their own tables and audit rows: nothing here records a disposition, changes a case status or
suppresses an alert. The model ranks; people decide.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from aml.cases.dispositions import SUSPICIOUS
from aml.cases.features import read_features, write_features
from aml.cases.labels import case_groups, has_ground_truth, truth_labels
from aml.cases.model import (
    PrioritizationError,
    check_groups,
    fit_model,
    predict,
    ranking_metrics,
)
from aml.cases.prio_store import (
    insert_model,
    insert_scores,
    latest_dispositions,
    latest_run,
    read_model,
    scalar,
)
from aml.cases.runner import CLOSED
from aml.cases.values import lower_columns
from aml.common.audit import AuditEvent, audit, audit_many
from aml.common.config import Settings
from aml.common.db import Database

__all__ = ["ScoringRun", "TrainingRun", "score", "train"]

KINDS = ("logreg", "lightgbm")


@dataclass(frozen=True)
class TrainingRun:
    model_id: int
    version: str  # "prio/<kind>/<model_id>"
    kind: str
    cases: int
    suspicious: int
    false_positive: int
    metrics: dict[str, Any]  # cross-validated ranking metrics


@dataclass(frozen=True)
class ScoringRun:
    score_run_id: int
    run_id: int  # the case run that was scored
    model_id: int
    version: str
    cases: int
    queue: int  # OPEN / REOPENED cases that got a queue rank
    holdout: dict[str, Any]  # metrics on the queue against the ground truth; {} without one


def _decided_groups(db: Database, decided: pd.DataFrame) -> pd.Series:
    """Group of every decided case, from the run it was decided on (reads only)."""
    parts = []
    for run_id, part in decided.groupby("run_id"):
        group_of = case_groups(db, int(run_id))
        ids = list(part["case_id"])
        parts.append(pd.Series([group_of[c] for c in ids], index=ids))
    return pd.concat(parts).sort_index()


def _training_set(db: Database, decided: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Features and labels of the decided cases, each from the snapshot it was decided on."""
    frames = []
    for run_id, part in decided.groupby("run_id"):
        run = int(run_id)
        write_features(db, run)  # stored once per run, never recomputed
        frames.append(read_features(db, run).loc[list(part["case_id"])])
    X = pd.concat(frames).sort_index()
    label = decided.set_index("case_id")["disposition"].eq(SUSPICIOUS).astype(int)
    return X, label.loc[X.index]


def train(
    db: Database, settings: Settings, *, kind: str | None = None, actor: str | None = None
) -> TrainingRun:
    """Fit a model on the latest decision of every labelled case and store it as a new version.

    The model row is written before its audit row, in two separate writes: a process that dies
    in between leaves a model without a ``MODEL_TRAINED`` audit row.
    """
    cfg = settings.cases.prioritization
    kind = kind or cfg.model
    if kind not in KINDS:
        raise PrioritizationError(f"unknown model kind {kind}: use one of {', '.join(KINDS)}")
    actor = actor or settings.audit.system_actor
    decided = latest_dispositions(db)
    suspicious = int((decided["disposition"] == SUSPICIOUS).sum())
    false_positive = len(decided) - suspicious
    if min(suspicious, false_positive) < cfg.cv_folds:  # checked before anything is written
        raise PrioritizationError(
            f"not enough labelled cases: need at least {cfg.cv_folds} per class, "
            f"got SUSPICIOUS={suspicious} FALSE_POSITIVE={false_positive}"
        )
    groups = _decided_groups(db, decided)
    check_groups(groups, cfg.cv_folds)  # also before anything is written
    X, y = _training_set(db, decided)
    model = fit_model(X, y, groups, cfg, seed=settings.seed, kind=kind)
    model_id, version = insert_model(
        db, kind=kind, seed=settings.seed, as_of=latest_run(db)[1],
        counts=(len(X), suspicious, false_positive), model=model, actor=actor,
    )  # fmt: skip
    m = model.metrics
    audit(
        db,
        module="cases",
        entity_type="model",
        entity_id=version,
        decision="MODEL_TRAINED",
        reason=(
            f"trained {kind} on {len(X)} labelled cases ({suspicious} SUSPICIOUS, "
            f"{false_positive} FALSE_POSITIVE; class_weight balanced): cross-validated "
            f"ROC-AUC {m['roc_auc']}, PR-AUC {m['pr_auc']}, prevalence {m['prevalence']}; "
            "ranking only"
        ),
        version=version,
        actor=actor,
        details={
            "model_id": model_id,
            "data_hash": model.data_hash,
            "metrics": m,
            "features": list(model.features),
        },
    )
    return TrainingRun(model_id, version, kind, len(X), suspicious, false_positive, m)


def _top_features(
    contributions: dict[str, float], values: pd.Series, n: int
) -> list[dict[str, Any]]:
    """The ``n`` features with the largest |contribution|; a tie goes to the smaller name."""
    rounded = {name: round(float(c), 4) for name, c in contributions.items()}
    names = sorted(rounded, key=lambda name: (-abs(rounded[name]), name))[:n]
    return [{"feature": f, "value": float(values[f]), "contribution": rounded[f]} for f in names]


def _rank(scores: dict[str, float], status: dict[str, str]) -> dict[str, int]:
    """Queue rank of the OPEN / REOPENED cases: score down, case id up (done in Python)."""
    queue = sorted((c for c in scores if status[c] != CLOSED), key=lambda c: (-scores[c], c))
    return {case_id: i for i, case_id in enumerate(queue, start=1)}


def _holdout(
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


def _case_event(
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


def score(
    db: Database, settings: Settings, *, model_id: int | None = None, actor: str | None = None
) -> ScoringRun:
    """Score every current case with a model (the newest by default) and store the ranking.

    The scores are written before the audit rows, in separate writes: a process that dies in
    between leaves a scoring run without its ``PRIORITIZED`` audit rows.
    """
    cfg = settings.cases.prioritization
    model_id, version, model = read_model(db, model_id)  # both errors come before any write
    run_id, _ = latest_run(db)
    write_features(db, run_id)
    cases = lower_columns(db.query_df(f"SELECT case_id, status FROM cases WHERE run_id = {run_id}"))
    status = dict(sorted(zip(cases["case_id"].astype(str), cases["status"], strict=True)))
    X = read_features(db, run_id)
    if missing := [c for c in status if c not in X.index]:
        raise PrioritizationError(
            f"case_features of run {run_id} lacks {len(missing)} case(s), e.g. {missing[0]}"
        )
    X = X.loc[list(status)]
    predicted = predict(model, X)
    scores = {c: round(float(s), 6) for c, s in predicted["score"].items()}
    rank = _rank(scores, status)
    top = cfg.top_features
    rows = [
        {
            "case_id": c,
            "score": scores[c],
            "queue_rank": rank.get(c),
            "top_features": _top_features(predicted.at[c, "contributions"], X.loc[c], top),
        }
        for c in status
    ]
    queued = {c: s for c, s in scores.items() if c in rank}
    score_run_id = 1 + scalar(db, "SELECT COALESCE(MAX(score_run_id), 0) FROM case_scores")
    run = ScoringRun(
        score_run_id, run_id, model_id, version, len(rows), len(rank),
        _holdout(db, settings, run_id, queued),
    )  # fmt: skip
    if rows:
        insert_scores(
            db,
            score_run_id=score_run_id,
            run_id=run_id,
            model_id=model_id,
            version=version,
            rows=rows,
        )
    events = [_case_event(r, len(rank), version, score_run_id, run_id, model_id) for r in rows]
    events.append(
        AuditEvent(
            module="cases",
            entity_type="case_run",
            entity_id=str(score_run_id),
            decision="SCORING_RUN_COMPLETED",
            reason=(
                f"Scored {run.cases} case(s) of run {run_id} with {version}: {run.queue} in the "
                "queue; ranking only, no disposition"
            ),
            version=version,
            details=asdict(run),
        )
    )
    if actor:
        events = [e.model_copy(update={"actor": actor}) for e in events]
    audit_many(db, events)
    return run
