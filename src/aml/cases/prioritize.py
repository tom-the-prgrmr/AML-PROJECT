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
from aml.cases.labels import case_groups
from aml.cases.model import (
    PrioritizationError,
    check_groups,
    fit_model,
    predict,
)
from aml.cases.prio_store import (
    insert_model,
    insert_scores,
    latest_dispositions,
    latest_run,
    read_model,
    scalar,
)
from aml.cases.scoring import case_event, holdout, queue_ranks, top_features
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

    The model row and its ``MODEL_TRAINED`` audit row are written in one transaction, so a model
    never becomes the active one without its audit record.
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
    m = model.metrics
    with db.transaction():
        model_id, version = insert_model(
            db, kind=kind, seed=settings.seed, as_of=latest_run(db)[1],
            counts=(len(X), suspicious, false_positive), model=model, actor=actor,
        )  # fmt: skip
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


def score(
    db: Database, settings: Settings, *, model_id: int | None = None, actor: str | None = None
) -> ScoringRun:
    """Score every current case with a model (the newest by default) and store the ranking.

    The scores and their ``PRIORITIZED`` audit rows are written in one transaction, so a score
    is never visible without its audit record.
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
    rank = queue_ranks(scores, status)
    top = cfg.top_features
    rows = [
        {
            "case_id": c,
            "score": scores[c],
            "queue_rank": rank.get(c),
            "top_features": top_features(predicted.at[c, "contributions"], X.loc[c], top),
        }
        for c in status
    ]
    queued = {c: s for c, s in scores.items() if c in rank}
    score_run_id = 1 + scalar(db, "SELECT COALESCE(MAX(score_run_id), 0) FROM case_scores")
    run = ScoringRun(
        score_run_id, run_id, model_id, version, len(rows), len(rank),
        holdout(db, settings, run_id, queued),
    )  # fmt: skip
    events = [case_event(r, len(rank), version, score_run_id, run_id, model_id) for r in rows]
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
    with db.transaction():
        if rows:
            insert_scores(
                db,
                score_run_id=score_run_id,
                run_id=run_id,
                model_id=model_id,
                version=version,
                rows=rows,
            )
        audit_many(db, events)
    return run
