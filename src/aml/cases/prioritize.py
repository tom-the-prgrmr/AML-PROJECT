"""Train and apply the case-ranking model, and audit every step.

`train` learns from the cases a person (or the simulation) has decided, on the feature snapshot the
decision saw. `score` ranks every current case and stores the score with its top factors. Both only
write their own tables and audit rows: nothing here records a disposition, changes a case status or
suppresses an alert. The model ranks; people decide.

Phase 8d adds six memo columns (`aml.memo.features`). They join the 35 case features only when
every memo of the training snapshots has a label; until then training is exactly as in Phase 7c.
Phase 7b-i adds two anomaly columns (`aml.ml.anomaly.case_features`) once an anomaly run exists
and `ml.anomaly.features` is `auto`; they are kept from ever lowering a score, like the risk memo
columns.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

import pandas as pd

from aml.cases.dispositions import SUSPICIOUS
from aml.cases.features import FEATURE_VERSION, read_features, write_features
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
from aml.memo.features import (
    MEMO_FEATURE_VERSION,
    MEMO_FEATURES,
    NON_NEGATIVE,
    decided_memo_features,
    ensure_memo_features,
    fit_guarded,
    memo_info,
)
from aml.memo.store import SCHEMA_MISSING, memo_schema_ready
from aml.ml.anomaly.case_features import (
    ANOMALY_CASE_FEATURES,
    ANOMALY_FEATURE_TAG,
    NON_NEGATIVE_ANOMALY,
    anomaly_info,
    current_anomaly_run,
    decided_anomaly_features,
    ensure_anomaly_features,
)

__all__ = ["LabelledSet", "ScoringRun", "TrainingRun", "labelled_set", "score", "train"]

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


@dataclass(frozen=True)
class LabelledSet:
    """The decided cases a model learns from: features, labels and the groups that share alerts."""

    X: pd.DataFrame
    y: pd.Series
    groups: pd.Series
    decided: pd.DataFrame  # case_id, disposition, run_id (the snapshot the decision saw)
    suspicious: int
    false_positive: int


def labelled_set(db: Database, settings: Settings) -> LabelledSet:
    """Read the training set; raises `PrioritizationError` before anything is written."""
    cfg = settings.cases.prioritization
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
    return LabelledSet(X, y, groups, decided, suspicious, false_positive)


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
    data = labelled_set(db, settings)
    X, y, groups = data.X, data.y, data.groups
    suspicious, false_positive = data.suspicious, data.false_positive
    use_memo = settings.memo.features == "auto"
    skipped = SCHEMA_MISSING if use_memo and not memo_schema_ready(db) else None
    use_memo = use_memo and skipped is None
    memo_columns = decided_memo_features(db, settings, data.decided) if use_memo else None
    use_anomaly = settings.ml.anomaly.features == "auto"
    anomaly_columns = decided_anomaly_features(db, settings, data.decided) if use_anomaly else None
    feature_version, memo, anomaly = FEATURE_VERSION, None, None
    if memo_columns is None and anomaly_columns is None:  # the Phase 7c model
        model = fit_model(X, y, groups, cfg, seed=settings.seed, kind=kind)
    else:
        if memo_columns is not None:
            X, feature_version = X.join(memo_columns), MEMO_FEATURE_VERSION
        if anomaly_columns is not None:
            X, feature_version = X.join(anomaly_columns), feature_version + ANOMALY_FEATURE_TAG
        model, dropped = fit_guarded(
            X, y, groups, cfg, seed=settings.seed, kind=kind,
            non_negative=NON_NEGATIVE + NON_NEGATIVE_ANOMALY,
        )  # fmt: skip
        params = model.params
        if memo_columns is not None:
            memo = memo_info(db, settings, tuple(d for d in dropped if d in MEMO_FEATURES))
            params = params | {"memo": memo}
        if anomaly_columns is not None:
            anomaly = anomaly_info(db, tuple(d for d in dropped if d in ANOMALY_CASE_FEATURES))
            params = params | {"anomaly": anomaly}
        model = replace(model, params=params)
    m = model.metrics
    with db.transaction():
        model_id, version = insert_model(
            db, kind=kind, seed=settings.seed, as_of=latest_run(db)[1],
            counts=(len(X), suspicious, false_positive), model=model, actor=actor,
            feature_version=feature_version,
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
            }
            | ({"memo": memo} if memo else {})
            | ({"anomaly": anomaly} if anomaly else {})
            | ({"memo_skipped": skipped} if skipped else {}),
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
    memo_source: str | None = None
    if set(model.features) & set(MEMO_FEATURES):
        # A run with a memo that has no label yet scores with zeros: a missing label must never
        # block the queue. Which one was used is written to the audit row.
        ready = memo_schema_ready(db)
        memo_columns = ensure_memo_features(db, settings, run_id) if ready else None
        memo_source = "zeros" if memo_columns is None else "stored"
        zeros = dict.fromkeys(MEMO_FEATURES, 0.0)
        X = X.assign(**zeros) if memo_columns is None else X.join(memo_columns)
    anomaly_used: dict[str, str | None] | None = None
    if set(model.features) & set(ANOMALY_CASE_FEATURES):
        # Scored with the current anomaly run, which may be newer than the one the model was
        # trained with; both versions go to the audit row and a missing run scores zeros.
        columns = ensure_anomaly_features(db, settings, run_id)
        current = current_anomaly_run(db)
        X = (
            X.assign(**dict.fromkeys(ANOMALY_CASE_FEATURES, 0.0))
            if columns is None
            else X.join(columns)
        )
        anomaly_used = {
            "trained_version": (model.params.get("anomaly") or {}).get("model_version"),
            "used_version": None if columns is None or current is None else current[1],
        }
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
            details=asdict(run)
            | ({"memo_features": memo_source} if memo_source else {})
            | ({"anomaly_features": anomaly_used} if anomaly_used else {}),
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
