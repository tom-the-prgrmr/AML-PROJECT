"""Measure the case ranking model on the below-the-line sample, and train the `+btl` variant.

`evaluate_btl` scores the sample with a stored model and stores the metrics: it writes no case
score and changes no queue. `train_with_btl` adds the sample to the decided cases and stores the
result as a new model version `prio/<kind>+btl/<id>`, which (as the newest) becomes the active
model. Both only rank and measure: no customer is alerted, cased, dispositioned or cleared.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from aml.cases.btl import (
    NOT_SUSPICIOUS,
    SUSPICIOUS,
    BtlSample,
    draw_sample,
    read_btl_features,
    write_btl_features,
)
from aml.cases.features import FEATURE_VERSION
from aml.cases.model import PrioritizationError, check_groups, fit_model, predict, ranking_metrics
from aml.cases.prio_store import insert_model, latest_run, read_model, scalar
from aml.cases.prioritize import KINDS, TrainingRun, labelled_set
from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database
from aml.memo.features import (
    MEMO_FEATURE_VERSION,
    MEMO_FEATURES,
    NON_NEGATIVE,
    decided_memo_features,
    fit_guarded,
    memo_info,
)
from aml.memo.store import SCHEMA_MISSING, memo_schema_ready
from aml.ml.anomaly.case_features import ANOMALY_CASE_FEATURES

__all__ = ["BtlEvaluation", "BtlTrainingRun", "evaluate_btl", "train_with_btl"]

ALERTED, BELOW_THE_LINE = "alerted", "below_the_line"
PREFIX = "btl:"  # row id (and group) of a sample member next to the case ids


@dataclass(frozen=True)
class BtlEvaluation:
    eval_id: int
    sample_id: int
    model_id: int
    version: str
    metrics: dict[str, Any]  # ranking metrics on the sample + population, estimated_missed, ci


@dataclass(frozen=True)
class BtlTrainingRun:
    training: TrainingRun  # version "prio/<kind>+btl/<model_id>"
    sample_id: int
    alerted: tuple[int, int]  # (SUSPICIOUS, FALSE_POSITIVE) of the decided cases
    below_the_line: tuple[int, int]  # (SUSPICIOUS, NOT_SUSPICIOUS) of the sample


def _labels(sample: BtlSample) -> pd.Series:
    """1 for a SUSPICIOUS member, 0 otherwise, indexed by golden customer id."""
    return pd.Series(
        [int(m.label == SUSPICIOUS) for m in sample.members],
        index=pd.Index([m.golden_customer_id for m in sample.members], name="golden_customer_id"),
        dtype=int,
    )


def _inputs(
    db: Database, settings: Settings, sample: BtlSample, features: tuple[str, ...]
) -> tuple[pd.DataFrame, dict[str, str]]:
    """The sample's features for a model; a column it was not computed for is zero, and said so."""
    X = read_btl_features(db, settings, sample.sample_id)
    assert X is not None  # without memo=True the frame always exists
    notes: dict[str, str] = {}
    if set(features) & set(MEMO_FEATURES):
        memo = read_btl_features(db, settings, sample.sample_id, memo=True)
        X = X.assign(**dict.fromkeys(MEMO_FEATURES, 0.0)) if memo is None else memo
        notes["memo_features"] = "zeros" if memo is None else "stored"
    if set(features) & set(ANOMALY_CASE_FEATURES):
        X = X.assign(**dict.fromkeys(ANOMALY_CASE_FEATURES, 0.0))
        notes["anomaly_features"] = "zeros"
    return X, notes


def evaluate_btl(
    db: Database, settings: Settings, *, model_id: int | None = None, actor: str | None = None
) -> BtlEvaluation:
    """Score the below-the-line sample with a stored model (the active one by default).

    The sample is drawn first if the case run has none yet. The metrics treat SUSPICIOUS as the
    positive class (``n_false_positive`` is the number of NOT_SUSPICIOUS members). Raises
    `PrioritizationError` without a model, before anything is written.
    """
    actor = actor or settings.audit.system_actor
    model_id, version, model = read_model(db, model_id)
    sample = draw_sample(db, settings, actor=actor)
    write_btl_features(db, settings, sample.sample_id)
    X, notes = _inputs(db, settings, sample, model.features)
    y = _labels(sample)
    scores = predict(model, X)["score"] if len(X) else pd.Series(dtype=float)
    metrics = ranking_metrics(y, scores, settings.cases.prioritization.top_fractions)
    metrics |= {
        "population": sample.population,
        "estimated_missed": sample.estimated_missed,
        "prevalence_ci95": list(sample.prevalence_ci95),
    }
    metrics = json.loads(json.dumps(metrics))  # what a reader of the stored row sees
    eval_id = 1 + scalar(db, "SELECT COALESCE(MAX(eval_id), 0) FROM btl_evaluations")
    row = {
        "eval_id": eval_id,
        "sample_id": sample.sample_id,
        "model_id": model_id,
        "model_version": version,
        "metrics": json.dumps(metrics),
        "scores": json.dumps({str(c): round(float(s), 6) for c, s in scores.items()}),
        "evaluated_ts": datetime.now(UTC).replace(tzinfo=None),
        "actor": actor,
    }
    with db.transaction():
        db.insert_df("btl_evaluations", pd.DataFrame([row]))
        audit(
            db,
            module="cases",
            entity_type="model",
            entity_id=version,
            decision="BTL_EVALUATED",
            reason=(
                f"measured {version} on below-the-line sample {sample.sample_id}: "
                f"{metrics['n']} customer(s), {metrics['n_suspicious']} suspicious, "
                f"ROC-AUC {metrics['roc_auc']}, PR-AUC {metrics['pr_auc']}; measurement only"
            ),
            version=version,
            actor=actor,
            details={
                "eval_id": eval_id,
                "sample_id": sample.sample_id,
                "model_id": model_id,
                "metrics": metrics,
            }
            | notes,
        )
    return BtlEvaluation(eval_id, sample.sample_id, model_id, version, metrics)


def _with_memo(
    db: Database,
    settings: Settings,
    sample: BtlSample,
    decided: pd.DataFrame,
    cases: pd.DataFrame,
    members: pd.DataFrame,
) -> pd.DataFrame | None:
    """Both parts with the six memo columns; None until every memo of both has a label."""
    member_memo = read_btl_features(db, settings, sample.sample_id, memo=True)
    case_memo = (
        decided_memo_features(db, settings, decided)
        if len(decided)
        else pd.DataFrame(columns=list(MEMO_FEATURES), dtype=float)
    )
    if member_memo is None or case_memo is None:
        return None
    member_memo = member_memo[list(MEMO_FEATURES)].rename(index=lambda g: PREFIX + str(g))
    return pd.concat([cases.join(case_memo), members.join(member_memo)])


def train_with_btl(
    db: Database, settings: Settings, *, kind: str | None = None, actor: str | None = None
) -> BtlTrainingRun:
    """Fit a model on the decided cases and the below-the-line sample, and store it as `+btl`.

    The sample members are extra rows (one group each) labelled from the ground truth; no sample
    weight is used. The class counts are checked over both parts before any model is written.
    The model row and its ``MODEL_TRAINED`` audit row are written in one transaction.
    """
    cfg = settings.cases.prioritization
    kind = kind or cfg.model
    if kind not in KINDS:
        raise PrioritizationError(f"unknown model kind {kind}: use one of {', '.join(KINDS)}")
    actor = actor or settings.audit.system_actor
    cases = labelled_set(db, settings, check=False)
    sample = draw_sample(db, settings, actor=actor)
    write_btl_features(db, settings, sample.sample_id)
    alerted = (cases.suspicious, cases.false_positive)
    below = (sample.suspicious, sample.not_suspicious)
    positives, negatives = alerted[0] + below[0], alerted[1] + below[1]
    if min(positives, negatives) < cfg.cv_folds:
        raise PrioritizationError(
            f"not enough labelled rows: need at least {cfg.cv_folds} per class, "
            f"got {SUSPICIOUS}={positives} {NOT_SUSPICIOUS}={negatives}"
        )
    y_btl = _labels(sample).rename(index=lambda g: PREFIX + str(g))
    groups = pd.concat([cases.groups, pd.Series(y_btl.index, index=y_btl.index)])
    check_groups(groups, cfg.cv_folds)
    members = read_btl_features(db, settings, sample.sample_id)
    assert members is not None
    members = members.rename(index=lambda g: PREFIX + str(g))
    skipped = None
    X = None
    if settings.memo.features == "auto":
        if memo_schema_ready(db):
            X = _with_memo(db, settings, sample, cases.decided, cases.X, members)
        else:
            skipped = SCHEMA_MISSING
    use_memo = X is not None
    if X is None:
        X = pd.concat([cases.X, members])
    y = pd.concat([cases.y, y_btl])
    populations = pd.Series([ALERTED] * len(cases.y) + [BELOW_THE_LINE] * len(y_btl), index=y.index)
    if use_memo:
        model, dropped = fit_guarded(
            X, y, groups, cfg, seed=settings.seed, kind=kind, non_negative=NON_NEGATIVE,
            populations=populations,
        )  # fmt: skip
        memo = memo_info(db, settings, tuple(d for d in dropped if d in MEMO_FEATURES))
        model = replace(model, params=model.params | {"memo": memo})
        feature_version = MEMO_FEATURE_VERSION
    else:
        model = fit_model(X, y, groups, cfg, seed=settings.seed, kind=kind, populations=populations)
        memo, feature_version = None, FEATURE_VERSION
    population = {
        ALERTED: list(alerted),
        BELOW_THE_LINE: list(below),
        "btl_sample_id": sample.sample_id,
    }
    model = replace(model, params=model.params | {"population": population})
    by_population = model.metrics["by_population"]
    with db.transaction():
        model_id, version = insert_model(
            db, kind=kind, seed=settings.seed, as_of=latest_run(db)[1],
            counts=(len(X), positives, negatives), model=model, actor=actor,
            feature_version=feature_version, variant="+btl",
        )  # fmt: skip
        audit(
            db,
            module="cases",
            entity_type="model",
            entity_id=version,
            decision="MODEL_TRAINED",
            reason=(
                f"trained {kind} on {sum(alerted)} labelled cases ({alerted[0]} SUSPICIOUS, "
                f"{alerted[1]} FALSE_POSITIVE) and {sum(below)} below-the-line customers "
                f"({below[0]} SUSPICIOUS, {below[1]} NOT_SUSPICIOUS; sample {sample.sample_id}; "
                "class_weight balanced): cross-validated ROC-AUC alerted "
                f"{by_population.get(ALERTED, {}).get('roc_auc')}, below-the-line "
                f"{by_population.get(BELOW_THE_LINE, {}).get('roc_auc')}; ranking only"
            ),
            version=version,
            actor=actor,
            details={
                "model_id": model_id,
                "data_hash": model.data_hash,
                "metrics": model.metrics,
                "features": list(model.features),
                "population": population,
            }
            | ({"memo": memo} if memo else {})
            | ({"memo_skipped": skipped} if skipped else {}),
        )
    run = TrainingRun(model_id, version, kind, len(X), positives, negatives, model.metrics)
    return BtlTrainingRun(run, sample.sample_id, alerted, below)
