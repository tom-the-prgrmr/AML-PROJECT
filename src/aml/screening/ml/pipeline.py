"""Train the match model on labelled screening pairs, and score every current hit with it.

The model only ranks: a score is stored next to the Tier 2 decision, which it never changes, and
nothing here clears or closes a hit. Both steps store what they did (rows plus audit rows) in one
transaction, and every audit row of a model carries the model version.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from aml.common.audit import AuditEvent, audit_many
from aml.common.config import Settings
from aml.common.db import Database
from aml.screening.evaluate import truth_pairs
from aml.screening.ml.features import FEATURE_VERSION, FEATURES, read_features, write_features
from aml.screening.ml.labels import HUMAN, MODULE, NO_SCREENING, training_labels
from aml.screening.ml.model import (
    MatchModel,
    ScreeningMlError,
    compare_at_recall,
    fit_match_model,
    predict,
)
from aml.screening.ml.store import count, json_value, next_id, run_query, text

__all__ = ["MatchScoringRun", "MatchTrainingRun", "read_model", "score", "train"]

KIND = "logreg"
NO_MODEL = "no model: run `aml screen-ml train` first"


@dataclass(frozen=True)
class MatchTrainingRun:
    model_id: int
    version: str  # scrml/logreg/<model_id>
    pairs: int
    true_match: int
    false_match: int
    human_labels: int
    metrics: dict[str, Any]


@dataclass(frozen=True)
class MatchScoringRun:
    score_run_id: int
    model_id: int
    version: str
    scored: int
    holdout: list[dict[str, Any]]  # comparison on the pairs without a training label; [] if none


def _actor(settings: Settings, actor: str | None) -> str:
    return actor or settings.audit.system_actor


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _training_frame(db: Database, settings: Settings) -> pd.DataFrame:
    """Labelled current pairs: index ``(cif, entry_id)``, features, label, origin, rule, run id."""
    features = read_features(db).reset_index().set_index(["cif", "entry_id"])
    decisions = run_query(db, "current_pairs").set_index(["cif", "entry_id"])["decision"]
    frame = features.join(training_labels(db, settings), how="inner")
    frame["rule"] = decisions.reindex(frame.index)
    return frame.sort_index()


def train(db: Database, settings: Settings, *, actor: str | None = None) -> MatchTrainingRun:
    """Fit a model on the labelled pairs and store it, its training set and one audit row.

    Raises `ScreeningMlError` (nothing is stored but missing features) when a class has fewer
    pairs than ``cv_folds`` or there is no screening result.
    """
    write_features(db, settings)
    frame = _training_frame(db, settings)
    groups = pd.Series(frame.index.get_level_values("entry_id"), index=frame.index)
    model = fit_match_model(
        frame[list(FEATURES)], frame["label"], groups, frame["rule"], settings.ml.screening,
        seed=settings.seed,
    )  # fmt: skip
    true_match = int(frame["label"].sum())
    human = int((frame["origin"] == HUMAN).sum())
    model_id = next_id(db, "screening_ml_models", "model_id")
    version = f"scrml/{KIND}/{model_id}"
    m = model.metrics
    row = {
        "model_id": model_id,
        "version": version,
        "feature_version": FEATURE_VERSION,
        "kind": KIND,
        "trained_ts": _utc_now(),
        "seed": settings.seed,
        "pairs": len(frame),
        "true_match": true_match,
        "false_match": len(frame) - true_match,
        "human_labels": human,
        "features": json.dumps(list(model.features)),
        "params": json.dumps(model.params),
        "metrics": json.dumps(model.metrics),
        "artifact": model.artifact,
        "data_hash": model.data_hash,
        "actor": _actor(settings, actor),
    }
    training = pd.DataFrame(
        {
            "model_id": model_id,
            "result_run_id": frame["result_run_id"].to_numpy(),
            "cif": frame.index.get_level_values("cif"),
            "entry_id": frame.index.get_level_values("entry_id"),
            "label": frame["label"].to_numpy(),
            "origin": frame["origin"].to_numpy(),
        }
    )
    event = AuditEvent(
        module=MODULE,
        entity_type="model",
        entity_id=version,
        decision="MODEL_TRAINED",
        reason=(
            f"trained logreg on {row['pairs']} labelled screening pairs ({true_match} TRUE_MATCH, "
            f"{row['false_match']} FALSE_MATCH, {human} from human reviews; class_weight "
            f"balanced): cross-validated ROC-AUC {m['roc_auc']}, PR-AUC {m['pr_auc']}; "
            "ranking only"
        ),
        version=version,
        actor=row["actor"],
        details={
            "model_id": model_id,
            "data_hash": model.data_hash,
            "metrics": model.metrics,
            "features": list(model.features),
        },
    )
    with db.transaction():
        db.insert_df("screening_ml_models", pd.DataFrame([row]))
        db.insert_df("screening_ml_training", training)
        audit_many(db, [event])
    return MatchTrainingRun(
        model_id, version, len(frame), true_match, len(frame) - true_match, human, model.metrics
    )


def read_model(db: Database, model_id: int | None = None) -> tuple[int, str, MatchModel]:
    """A stored model by id, or the newest one; `ScreeningMlError` when there is none."""
    df = (
        run_query(db, "model_active")
        if model_id is None
        else run_query(db, "model_by_id", model_id=model_id)
    )
    if df.empty:
        raise ScreeningMlError(NO_MODEL if model_id is None else f"unknown model_id {model_id}")
    r = df.iloc[0]
    model = MatchModel(
        features=tuple(json_value(r["features"])),
        artifact=text(r["artifact"]),
        params=json_value(r["params"]),
        metrics=json_value(r["metrics"]),
        data_hash=str(r["data_hash"]),
    )
    return int(r["model_id"]), str(r["version"]), model


def _top_features(
    contributions: dict[str, float], values: pd.Series, top: int
) -> list[dict[str, Any]]:
    order = sorted(contributions, key=lambda f: (-abs(contributions[f]), f))[:top]
    return [
        {"feature": f, "value": float(values[f]), "contribution": round(contributions[f], 4)}
        for f in order
    ]


def _holdout(db: Database, settings: Settings, scored: pd.DataFrame) -> list[dict[str, Any]]:
    """Rule versus model on the pairs the model was not trained on; truth is used to measure."""
    if count(db, "ground_truth") == 0:
        return []
    pairs = pd.MultiIndex.from_arrays([scored["cif"], scored["entry_id"]])
    unlabelled = scored[~pairs.isin(training_labels(db, settings).index)]
    if unlabelled.empty:
        return []
    truth = truth_pairs(db)
    index = pd.MultiIndex.from_arrays([unlabelled["cif"], unlabelled["entry_id"]])
    y = pd.Series([p in truth for p in index], index=index)
    comparison = compare_at_recall(
        y, pd.Series(unlabelled["score"].to_numpy(), index=index),
        pd.Series(unlabelled["system_decision"].to_numpy(), index=index),
    )  # fmt: skip
    return list(comparison.to_dict("records"))


def _score_event(row: Any, run: MatchScoringRun, n: int) -> AuditEvent:
    factors = ", ".join(f"{t['feature']} {t['contribution']:+.2f}" for t in row.top_features)
    return AuditEvent(
        module=MODULE,
        entity_type="screening_ml_score",
        entity_id=f"{row.cif}:{row.entry_id}",
        decision="ML_SCORED",
        reason=(
            f"match score {row.score:.4f} from {run.version}, rank {row.score_rank} of {n}; "
            f"system decision {row.system_decision} unchanged; top factors: {factors}; "
            "ranking only, no clearance"
        ),
        version=run.version,
        actor=row.actor,
        details={
            "score_run_id": run.score_run_id,
            "model_id": run.model_id,
            "result_run_id": int(row.result_run_id),
            "score": row.score,
            "score_rank": int(row.score_rank),
            "system_decision": row.system_decision,
            "top_features": row.top_features,
        },
    )


def score(
    db: Database, settings: Settings, *, model_id: int | None = None, actor: str | None = None
) -> MatchScoringRun:
    """Score every current hit with a stored model (the newest by default) and store the scores.

    The Tier 2 decision of a hit is read, shown in the audit reason and left as it is.
    """
    model_id, version, model = read_model(db, model_id)
    write_features(db, settings)
    X = read_features(db)
    if X.empty:
        raise ScreeningMlError(NO_SCREENING)
    pred = predict(model, X)
    decisions = run_query(db, "current_pairs").set_index(["cif", "entry_id"])["decision"]
    scored = X.reset_index()[["result_run_id", "cif", "entry_id"]]
    scored["score"] = pred["score"].round(6).to_numpy()
    scored["system_decision"] = decisions.reindex(
        pd.MultiIndex.from_arrays([scored["cif"], scored["entry_id"]])
    ).to_numpy()
    scored = scored.sort_values(["score", "cif", "entry_id"], ascending=[False, True, True])
    scored["score_rank"] = range(1, len(scored) + 1)
    top = settings.ml.screening.top_features
    values = X.reset_index(drop=True)
    contributions = pred["contributions"].reset_index(drop=True)
    scored["top_features"] = [
        _top_features(contributions[i], values.loc[i], top) for i in scored.index
    ]
    scored["actor"] = _actor(settings, actor)
    run = MatchScoringRun(
        next_id(db, "screening_ml_scores", "score_run_id"),
        model_id,
        version,
        len(scored),
        _holdout(db, settings, scored),
    )
    now = _utc_now()
    table = pd.DataFrame(
        {
            "score_run_id": run.score_run_id,
            "result_run_id": scored["result_run_id"].to_numpy(),
            "cif": scored["cif"].to_numpy(),
            "entry_id": scored["entry_id"].to_numpy(),
            "model_id": model_id,
            "model_version": version,
            "score": scored["score"].to_numpy(),
            "score_rank": scored["score_rank"].to_numpy(),
            "top_features": [json.dumps(t) for t in scored["top_features"]],
            "scored_ts": now,
        }
    )
    events = [_score_event(row, run, len(scored)) for row in scored.itertuples()]
    events.append(
        AuditEvent(
            module=MODULE,
            entity_type="screening_ml_run",
            entity_id=str(run.score_run_id),
            decision="ML_SCORING_COMPLETED",
            reason=(
                f"scored {run.scored} current screening hits with {version}; Tier 2 decisions "
                "unchanged; ranking only, no clearance"
            ),
            version=version,
            actor=_actor(settings, actor),
            details=asdict(run),
        )
    )
    with db.transaction():
        db.insert_df("screening_ml_scores", table)
        audit_many(db, events)
    return run
