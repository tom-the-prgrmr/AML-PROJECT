"""`aml memo compare`: does the ranking model get better with the memo columns? An honest answer.

Two models are fitted on the same decided cases, the same folds and the same seed: one on the 35
case features, one on those plus the memo columns (`fit_guarded`). Nothing is stored: no model, no
score. The gambling-like and crypto-like memos were planted on purpose in the suspicious scenarios
of the synthetic data, so a gain here shows that the plumbing works, not that memos predict risk.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from aml.cases.chain import POPULATION
from aml.cases.features import read_features, write_features
from aml.cases.model import PrioritizationError, TrainedModel, predict
from aml.cases.prio_store import latest_run
from aml.cases.prioritize import KINDS, labelled_set
from aml.cases.scoring import holdout, queue_ranks
from aml.cases.values import lower_columns
from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database
from aml.memo.classify import MemoError
from aml.memo.features import (
    MEMO_FEATURES,
    decided_memo_features,
    delta,
    ensure_memo_features,
    fit_pair,
)
from aml.memo.normalize import MEMO_VERSION
from aml.memo.store import MODULE, by_category, by_method, labels_rev, read_labels

NOT_AVAILABLE = "memo features are not available: run `aml memo classify` first"


def _holdout(
    db: Database, settings: Settings, run_id: int, model: TrainedModel, X: pd.DataFrame
) -> dict[str, Any]:
    """Queue metrics of the current run, measured the way `aml score` measures them."""
    cases = lower_columns(db.query_df(f"SELECT case_id, status FROM cases WHERE run_id = {run_id}"))
    status = dict(sorted(zip(cases["case_id"].astype(str), cases["status"], strict=True)))
    predicted = predict(model, X.loc[list(status)])
    scores = {c: round(float(s), 6) for c, s in predicted["score"].items()}
    rank = queue_ranks(scores, status)
    return holdout(db, settings, run_id, {c: s for c, s in scores.items() if c in rank})


def compare_memo_features(
    db: Database, settings: Settings, *, kind: str | None = None, actor: str | None = None
) -> dict[str, Any]:
    """Measure the ranking model with and without memo features; store neither model.

    Raises `PrioritizationError` when there is no case run or too few decided cases, and
    `MemoError` when a memo of the cases has no label yet. Writes one audit row.
    """
    cfg = settings.cases.prioritization
    kind = kind or cfg.model
    if kind not in KINDS:
        raise PrioritizationError(f"unknown model kind {kind}: use one of {', '.join(KINDS)}")
    run_id, _ = latest_run(db)
    data = labelled_set(db, settings)
    memo_train = decided_memo_features(db, settings, data.decided)
    memo_now = ensure_memo_features(db, settings, run_id)
    if memo_train is None or memo_now is None:
        raise MemoError(NOT_AVAILABLE)
    base, with_memo, dropped = fit_pair(
        data.X, data.X.join(memo_train), data.y, data.groups, cfg, seed=settings.seed, kind=kind
    )
    write_features(db, run_id)  # the feature snapshot of the current run (stored once)
    X_now = read_features(db, run_id)
    hold_base = _holdout(db, settings, run_id, base, X_now)
    hold_memo = _holdout(db, settings, run_id, with_memo, X_now.join(memo_now))
    labels = read_labels(db, settings)
    payload: dict[str, Any] = {
        "memo": {
            "version": MEMO_VERSION,
            "model": settings.ollama.llm_model,
            "keys": len(labels),
            "labels_rev": labels_rev(db),
            "by_method": by_method(labels),
            "by_category": by_category(labels),
        },
        "data": {
            "cases": len(data.X),
            "suspicious": data.suspicious,
            "false_positive": data.false_positive,
            "cases_with_memo": int((memo_train["memo_txns"] > 0).sum()),
            "nonzero": {name: int((memo_train[name] != 0).sum()) for name in MEMO_FEATURES},
        },
        "base": {"features": len(base.features), "cv": base.metrics, "holdout": hold_base},
        "with_memo": {
            "features": len(with_memo.features),
            "dropped_features": list(dropped),
            "cv": with_memo.metrics,
            "holdout": hold_memo,
        },
        "delta": delta(with_memo.metrics, base.metrics, "cv")
        | delta(hold_memo, hold_base, "holdout"),
        "population": POPULATION,
    }
    cv_base, cv_memo = base.metrics["roc_auc"], with_memo.metrics["roc_auc"]
    audit(
        db,
        module=MODULE,
        entity_type="model_comparison",
        entity_id=str(run_id),
        decision="MEMO_FEATURES_COMPARED",
        reason=(
            "compared the ranking model with and without memo features on "
            f"{len(data.X)} labelled cases: cross-validated ROC-AUC {cv_base} vs {cv_memo} "
            f"(delta {payload['delta']['cv_roc_auc']}); measurement only, no model stored"
        ),
        version=MEMO_VERSION,
        actor=actor or settings.audit.system_actor,
        details={
            "kind": kind,
            "memo": payload["memo"],
            "data": payload["data"],
            "delta": payload["delta"],
            "dropped_features": list(dropped),
        },
    )
    return payload
