"""The ranking model: fit on labelled cases, score any case, explain each score.

Pure: it takes frames and returns frames, with no database access. Logistic regression is the
default; its artifact is plain JSON, so a score can be recomputed with NumPy alone. LightGBM is an
optional extra (`uv sync --extra ml`). Both use ``class_weight="balanced"`` to cope with the
imbalance between the two classes (no oversampling). The model only ranks; it never decides.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit

from aml.cases.ranking import ranking_metrics
from aml.common.config import PrioritizationConfig

__all__ = [
    "PrioritizationError",
    "TrainedModel",
    "check_groups",
    "cv_splits",
    "fit_model",
    "predict",
    "ranking_metrics",
]

LIGHTGBM_MISSING = "lightgbm is not installed: uv sync --extra ml"


class PrioritizationError(RuntimeError):
    """Prioritization cannot run with the data or the model it was given."""


@dataclass(frozen=True)
class TrainedModel:
    kind: str  # "logreg" | "lightgbm"
    features: tuple[str, ...]
    artifact: str  # logreg: JSON {features, mean, scale, coef, intercept}; lightgbm: model text
    params: dict[str, Any]
    metrics: dict[str, Any]  # cross-validated `ranking_metrics`
    data_hash: str  # 16 hex characters
    feature_version: str = "unknown"  # set when a stored model is read back


def _data_hash(X: pd.DataFrame, y: pd.Series) -> str:
    """Hash of the feature names, the case ids, the matrix (rounded to 10) and the labels.

    ``X`` and ``y`` are already sorted by case id, so the row order of the caller does not matter.
    Adding 0.0 turns -0.0 into 0.0 so a sign artefact cannot change the hash.
    """
    matrix = np.round(X.to_numpy(dtype="<f8"), 10) + 0.0
    digest = hashlib.sha256()
    digest.update(json.dumps([list(X.columns), [str(i) for i in X.index]]).encode("utf-8"))
    digest.update(np.ascontiguousarray(matrix).tobytes())
    digest.update(y.to_numpy(dtype="int8").tobytes())
    return digest.hexdigest()[:16]


def _lightgbm() -> Any:
    try:
        import lightgbm
    except ImportError as exc:
        raise PrioritizationError(LIGHTGBM_MISSING) from exc
    return lightgbm


def _fit_artifact(
    kind: str, X: pd.DataFrame, y: pd.Series, cfg: PrioritizationConfig, seed: int
) -> str:
    """Fit on all of ``X`` and return the artifact text."""
    if kind == "lightgbm":
        lgb = _lightgbm()
        g = cfg.lightgbm
        clf = lgb.LGBMClassifier(
            class_weight="balanced", random_state=seed, deterministic=True, force_row_wise=True,
            n_jobs=1, verbose=-1, n_estimators=g.n_estimators, num_leaves=g.num_leaves,
            learning_rate=g.learning_rate, min_child_samples=g.min_child_samples,
        )  # fmt: skip
        clf.fit(X.to_numpy(dtype=float), y.to_numpy())
        return str(clf.booster_.model_to_string())
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(X.to_numpy(dtype=float))
    clf = LogisticRegression(
        C=cfg.logreg.c, max_iter=cfg.logreg.max_iter, class_weight="balanced", solver="lbfgs",
        random_state=seed,
    )  # fmt: skip
    clf.fit(scaler.transform(X.to_numpy(dtype=float)), y.to_numpy())
    return json.dumps(
        {
            "features": list(X.columns),
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
            "coef": clf.coef_[0].tolist(),
            "intercept": float(clf.intercept_[0]),
        }
    )


def _contributions(kind: str, artifact: str, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Per-feature contributions (n x features) and the base value (n) on the log-odds scale."""
    if kind == "lightgbm":
        booster = _lightgbm().Booster(model_str=artifact)
        raw = booster.predict(X.to_numpy(dtype=float), pred_contrib=True)
        return raw[:, :-1], raw[:, -1]
    a = json.loads(artifact)
    x = X[a["features"]].to_numpy(dtype=float)
    contributions = np.asarray(a["coef"]) * (x - np.asarray(a["mean"])) / np.asarray(a["scale"])
    return contributions, np.full(len(x), float(a["intercept"]))


def _scores(kind: str, artifact: str, X: pd.DataFrame) -> np.ndarray:
    contributions, base = _contributions(kind, artifact, X)
    return np.asarray(expit(contributions.sum(axis=1) + base))


def check_groups(groups: pd.Series, cv_folds: int) -> None:
    """Grouped cross-validation needs at least ``cv_folds`` groups; checked before any write."""
    n = int(groups.nunique())
    if n < cv_folds:
        raise PrioritizationError(f"not enough labelled groups: need at least {cv_folds}, got {n}")


def cv_splits(
    X: pd.DataFrame, y: pd.Series, groups: pd.Series, cfg: PrioritizationConfig, seed: int
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Positional (train, test) index pairs; a group (cases that share alerts) is never split."""
    from sklearn.model_selection import StratifiedGroupKFold

    folds = StratifiedGroupKFold(n_splits=cfg.cv_folds, shuffle=True, random_state=seed)
    return list(folds.split(X, y, groups))


def _cross_validate(
    kind: str,
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    cfg: PrioritizationConfig,
    seed: int,
) -> pd.Series:
    """Out-of-fold score of every case."""
    oof = pd.Series(np.nan, index=X.index)
    for train, test in cv_splits(X, y, groups, cfg, seed):
        if y.iloc[train].nunique() < 2:
            raise PrioritizationError("a cross-validation fold has only one class")
        artifact = _fit_artifact(kind, X.iloc[train], y.iloc[train], cfg, seed)
        oof.iloc[test] = _scores(kind, artifact, X.iloc[test])
    return oof


def _versions(kind: str) -> dict[str, str]:
    import sklearn

    versions = {"sklearn": sklearn.__version__}
    if kind == "lightgbm":
        versions["lightgbm"] = str(_lightgbm().__version__)
    return versions


def fit_model(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    cfg: PrioritizationConfig,
    *,
    seed: int,
    kind: str | None = None,
    populations: pd.Series | None = None,
) -> TrainedModel:
    """Fit a model on labelled cases and measure it by grouped cross-validation.

    ``X`` is indexed by case id, ``y`` is 1 for SUSPICIOUS and 0 for FALSE_POSITIVE, ``groups``
    ties together the cases that share alerts. Rows are sorted by case id first, so the order the
    caller passes them in changes neither the folds nor the model.

    ``populations`` (same index as ``X``; a name per row) adds ``by_population`` to the metrics:
    the ranking metrics of each population's own out-of-fold scores. It changes nothing else.
    """
    kind = kind or cfg.model
    X = X.sort_index()
    y = y.loc[X.index].astype(int)
    groups = groups.loc[X.index]
    suspicious, false_positive = int((y == 1).sum()), int((y == 0).sum())
    if min(suspicious, false_positive) < cfg.cv_folds:
        raise PrioritizationError(
            f"not enough labelled cases: need at least {cfg.cv_folds} per class, "
            f"got SUSPICIOUS={suspicious} FALSE_POSITIVE={false_positive}"
        )
    check_groups(groups, cfg.cv_folds)
    oof = _cross_validate(kind, X, y, groups, cfg, seed)
    metrics = ranking_metrics(y, oof, cfg.top_fractions)
    if populations is not None:
        named = populations.loc[X.index]
        metrics["by_population"] = {
            name: ranking_metrics(y[named == name], oof[named == name], cfg.top_fractions)
            for name in sorted(set(named))
        }
    params: dict[str, Any] = {"class_weight": "balanced", "cv_folds": cfg.cv_folds}
    params |= cfg.lightgbm.model_dump() if kind == "lightgbm" else cfg.logreg.model_dump()
    params |= _versions(kind)
    return TrainedModel(
        kind=kind,
        features=tuple(X.columns),
        artifact=_fit_artifact(kind, X, y, cfg, seed),
        params=params,
        metrics=metrics,
        data_hash=_data_hash(X, y),
    )


def predict(model: TrainedModel, X: pd.DataFrame) -> pd.DataFrame:
    """Score (0..1) and per-feature contributions (log-odds) of every row of ``X``.

    For logistic regression the contributions plus the intercept add up to the log-odds of the
    score; for LightGBM they plus the base value do. The score is a ranking value, not a calibrated
    probability.
    """
    missing = [f for f in model.features if f not in X.columns]
    if missing:
        raise PrioritizationError(
            f"model with feature_version {model.feature_version} needs features this data lacks: "
            f"{', '.join(missing)}; retrain with `aml cases train`"
        )
    X = X[list(model.features)]
    contributions, base = _contributions(model.kind, model.artifact, X)
    return pd.DataFrame(
        {
            "score": np.asarray(expit(contributions.sum(axis=1) + base)),
            "contributions": [
                dict(zip(model.features, row.tolist(), strict=True)) for row in contributions
            ],
        },
        index=X.index,
    )
