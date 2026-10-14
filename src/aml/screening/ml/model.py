"""The match model: fit on labelled screening pairs, score any pair, explain each score.

Pure: it takes frames and returns frames, with no storage access. The artifact is plain JSON
(standardiser plus logistic regression coefficients), so a score can be recomputed with NumPy
alone. The model only ranks pairs; the comparison with the fixed thresholds is a measurement.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit

from aml.common.config import ScreeningMlConfig

__all__ = [
    "BASELINES",
    "COMPARE_COLUMNS",
    "MatchModel",
    "ScreeningMlError",
    "compare_at_recall",
    "fit_match_model",
    "predict",
]

COMPARE_COLUMNS = [
    "baseline", "pairs", "positives", "rule_flagged", "rule_tp", "rule_precision",
    "rule_recall", "model_flagged", "model_tp", "model_precision", "model_recall",
    "flagged_reduction_pct",
]  # fmt: skip
# baseline name -> Tier 2 decisions the fixed thresholds flag
BASELINES: dict[str, tuple[str, ...]] = {
    "two_tier_alert": ("ALERT",),
    "two_tier": ("ALERT", "REVIEW"),
}


class ScreeningMlError(RuntimeError):
    """The screening model cannot be built or used with the data it was given."""


@dataclass(frozen=True)
class MatchModel:
    features: tuple[str, ...]
    artifact: str  # JSON {features, mean, scale, coef, intercept}
    params: dict[str, Any]
    metrics: dict[str, Any]  # {n, n_true, n_false, prevalence, roc_auc, pr_auc, comparison}
    data_hash: str  # 16 hex characters


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def compare_at_recall(y: pd.Series, score: pd.Series, rule: pd.Series) -> pd.DataFrame:
    """Hits to look at, rule versus model, for the same number of true matches found.

    For each baseline the rule flags ``ALERT`` (or ``ALERT`` and ``REVIEW``) pairs and finds
    ``rule_tp`` true matches. The model flags nothing: its top-k is only a way to measure, with
    k the smallest number of best-scored pairs that contain at least ``rule_tp`` true matches.
    Ties in score are broken by the index, so the result is deterministic.
    """
    frame = pd.DataFrame({"y": y.astype(int), "rule": rule, "score": score}).sort_index()
    frame = frame.sort_values("score", ascending=False, kind="stable")
    found = frame["y"].cumsum().to_numpy()
    positives, pairs = int(frame["y"].sum()), len(frame)
    rows = []
    for name, decisions in BASELINES.items():
        flagged = frame["rule"].isin(decisions)
        rule_flagged, rule_tp = int(flagged.sum()), int((flagged & (frame["y"] == 1)).sum())
        k = int(np.searchsorted(found, rule_tp) + 1) if rule_tp else 0
        model_tp = int(found[k - 1]) if k else 0
        rows.append(
            {
                "baseline": name,
                "pairs": pairs,
                "positives": positives,
                "rule_flagged": rule_flagged,
                "rule_tp": rule_tp,
                "rule_precision": _ratio(rule_tp, rule_flagged),
                "rule_recall": _ratio(rule_tp, positives),
                "model_flagged": k,
                "model_tp": model_tp,
                "model_precision": _ratio(model_tp, k),
                "model_recall": _ratio(model_tp, positives),
                "flagged_reduction_pct": (
                    round(100 * (1 - k / rule_flagged), 2) if rule_flagged else None
                ),
            }
        )
    df = pd.DataFrame(rows, columns=COMPARE_COLUMNS).astype(object)
    return df.where(df.notna(), None)


def _data_hash(X: pd.DataFrame, y: pd.Series) -> str:
    """Hash of the feature names, the pair keys, the matrix (rounded to 10) and the labels.

    ``X`` and ``y`` are already sorted by key. Adding 0.0 turns -0.0 into 0.0.
    """
    matrix = np.round(X.to_numpy(dtype="<f8"), 10) + 0.0
    digest = hashlib.sha256()
    digest.update(json.dumps([list(X.columns), [str(i) for i in X.index]]).encode("utf-8"))
    digest.update(np.ascontiguousarray(matrix).tobytes())
    digest.update(y.to_numpy(dtype="int8").tobytes())
    return digest.hexdigest()[:16]


def _logreg(cfg: ScreeningMlConfig, seed: int) -> Any:
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(
        C=cfg.logreg.c, max_iter=cfg.logreg.max_iter, class_weight="balanced", solver="lbfgs",
        random_state=seed,
    )  # fmt: skip


def _out_of_fold(
    X: pd.DataFrame, y: pd.Series, groups: pd.Series, cfg: ScreeningMlConfig, seed: int
) -> np.ndarray:
    """Score of every pair from a model that did not see its group (all pairs of one entry)."""
    from sklearn.model_selection import StratifiedGroupKFold
    from sklearn.preprocessing import StandardScaler

    oof = np.full(len(X), np.nan)
    folds = StratifiedGroupKFold(n_splits=cfg.cv_folds, shuffle=True, random_state=seed)
    values = X.to_numpy(dtype=float)
    for train, test in folds.split(values, y.to_numpy(), groups.to_numpy()):
        if y.iloc[train].nunique() < 2:
            raise ScreeningMlError("a cross-validation fold has only one class")
        scaler = StandardScaler().fit(values[train])
        clf = _logreg(cfg, seed).fit(scaler.transform(values[train]), y.iloc[train])
        oof[test] = clf.predict_proba(scaler.transform(values[test]))[:, 1]
    return oof


def fit_match_model(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    rule: pd.Series,
    cfg: ScreeningMlConfig,
    *,
    seed: int,
) -> MatchModel:
    """Fit on labelled pairs and measure the model by grouped cross-validation.

    ``y`` is 1 for TRUE_MATCH, ``groups`` is the entry of each pair (so a person with several
    CIFs never sits on both sides of a split) and ``rule`` is the Tier 2 decision, used only to
    build the comparison. Rows are sorted by index first, so the caller's order changes nothing.
    """
    import sklearn
    from sklearn.metrics import average_precision_score, roc_auc_score
    from sklearn.preprocessing import StandardScaler

    X = X.sort_index()
    y, groups, rule = (s.loc[X.index] for s in (y.astype(int), groups, rule))
    n_true, n_false = int((y == 1).sum()), int((y == 0).sum())
    if min(n_true, n_false) < cfg.cv_folds:
        raise ScreeningMlError(
            f"not enough labelled pairs: need at least {cfg.cv_folds} per class, "
            f"got TRUE_MATCH={n_true} FALSE_MATCH={n_false}"
        )
    if groups.nunique() < cfg.cv_folds:
        raise ScreeningMlError(
            f"not enough labelled entries: need at least {cfg.cv_folds}, got {groups.nunique()}"
        )
    oof = pd.Series(_out_of_fold(X, y, groups, cfg, seed), index=X.index)
    scaler = StandardScaler().fit(X.to_numpy(dtype=float))
    clf = _logreg(cfg, seed).fit(scaler.transform(X.to_numpy(dtype=float)), y)
    artifact = json.dumps(
        {
            "features": list(X.columns),
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
            "coef": clf.coef_[0].tolist(),
            "intercept": float(clf.intercept_[0]),
        }
    )
    metrics: dict[str, Any] = {
        "n": len(X),
        "n_true": n_true,
        "n_false": n_false,
        "prevalence": round(n_true / len(X), 4),
        "roc_auc": round(float(roc_auc_score(y, oof)), 4),
        "pr_auc": round(float(average_precision_score(y, oof)), 4),
        "comparison": compare_at_recall(y, oof, rule).to_dict("records"),
    }
    params = {
        "c": cfg.logreg.c,
        "max_iter": cfg.logreg.max_iter,
        "class_weight": "balanced",
        "solver": "lbfgs",
        "cv_folds": cfg.cv_folds,
        "seed": seed,
        "sklearn": sklearn.__version__,
    }
    return MatchModel(tuple(X.columns), artifact, params, metrics, _data_hash(X, y))


def predict(model: MatchModel, X: pd.DataFrame) -> pd.DataFrame:
    """Score (0..1) and per-feature contributions (log-odds) of every row of ``X``.

    The contributions plus the intercept add up to the log-odds of the score. The score is a
    ranking value: the balanced class weights make it differ from a calibrated probability.
    """
    missing = [f for f in model.features if f not in X.columns]
    if missing:
        raise ScreeningMlError(f"model needs features this data lacks: {', '.join(missing)}")
    a = json.loads(model.artifact)
    x = X[list(model.features)].to_numpy(dtype=float)
    contributions = np.asarray(a["coef"]) * (x - np.asarray(a["mean"])) / np.asarray(a["scale"])
    score = expit(contributions.sum(axis=1) + float(a["intercept"]))
    return pd.DataFrame(
        {
            "score": np.asarray(score),
            "contributions": [
                dict(zip(model.features, row.tolist(), strict=True)) for row in contributions
            ],
        },
        index=X.index,
    )
