"""The isolation forest and the small pure helpers around it. The only module that imports sklearn.

The model is unsupervised: it is fitted on all samples of a run and scores those same samples, so
a score only says how unusual a customer-month is among its peers of that run, never whether it is
suspicious. Everything here is deterministic for a given matrix, configuration and seed.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

import numpy as np
import pandas as pd

from aml.common.config import AnomalyConfig

SCORE_DECIMALS = 6
METRIC_PERCENTILES = {"p25": 25, "p50": 50, "p75": 75, "p90": 90, "p99": 99}


def iforest_params(cfg: AnomalyConfig, rows: int, *, seed: int) -> dict[str, Any]:
    """The parameters `IsolationForest` is built with (also stored with the run)."""
    return {
        "n_estimators": cfg.n_estimators,
        "max_samples": min(cfg.max_samples, rows),
        "max_features": 1.0,
        "bootstrap": False,
        "random_state": seed,
        "n_jobs": 1,
    }


def library_versions() -> dict[str, str]:
    """What a run needs to be reproduced: scores can differ between library versions."""
    import sklearn  # lazy: importing the CLI must not load scikit-learn

    return {"sklearn_version": sklearn.__version__, "numpy_version": np.__version__}


def fit_score(X: pd.DataFrame, cfg: AnomalyConfig, *, seed: int) -> pd.Series:
    """Fit on every row of ``X`` and score those rows: higher = more unusual, in (0, 1]."""
    if len(X) < 2:
        raise ValueError(f"need at least 2 rows to fit an isolation forest, got {len(X)}")
    from sklearn.ensemble import IsolationForest  # lazy, like aml.cases.model

    forest = IsolationForest(**iforest_params(cfg, len(X), seed=seed))
    forest.fit(X.to_numpy(dtype="float64"))
    scores = -forest.score_samples(X.to_numpy(dtype="float64"))
    return pd.Series(np.round(scores, SCORE_DECIMALS), index=X.index, name="score")


def rank_scores(scores: pd.Series) -> pd.Series:
    """Rank 1..n by score (highest first), then cif, then month, so a tie never depends on order."""
    table = pd.DataFrame(
        {
            "score": scores.to_numpy(),
            "cif": scores.index.get_level_values("cif"),
            "month": scores.index.get_level_values("month"),
        }
    )
    order = table.sort_values(["score", "cif", "month"], ascending=[False, True, True]).index
    ranks = np.empty(len(table), dtype="int64")
    ranks[np.asarray(order)] = np.arange(1, len(table) + 1)
    return pd.Series(ranks, index=scores.index, name="rank")


def alert_count(n: int, fraction: float) -> int:
    """Samples that alert: ceil(fraction * n), that many even when nothing is unusual."""
    return 0 if n == 0 else math.ceil(round(fraction * n, 9))


def top_deviations(X: pd.DataFrame, key: tuple[str, str], k: int) -> list[dict[str, Any]]:
    """The ``k`` features of one sample that sit furthest from the median, in IQR units.

    z = (x - median) / IQR over all samples of the run (IQR 0 divides by 1). Ties keep the order of
    the columns.
    """
    spread = X.quantile(0.75) - X.quantile(0.25)
    median = X.median()
    z = (X.loc[key] - median) / spread.where(spread != 0, 1.0)
    order = np.argsort(-np.abs(z.to_numpy(dtype="float64")), kind="stable")[:k]
    return [
        {
            "feature": str(X.columns[i]),
            "value": round(float(X.loc[key].iloc[i]), 4),
            "median": round(float(median.iloc[i]), 4),
            "z": round(float(z.iloc[i]), 4),
        }
        for i in order
    ]


def data_hash(X: pd.DataFrame) -> str:
    """First 16 hex characters of the SHA-256 of the matrix as CSV (index cif, month)."""
    return hashlib.sha256(X.to_csv().encode("utf-8")).hexdigest()[:16]


def score_metrics(scores: pd.Series) -> dict[str, float]:
    """Distribution of the scores of a run: min, percentiles and max (no right / wrong exists)."""
    values = scores.to_numpy(dtype="float64")
    out = {"min": float(values.min())}
    for name, q in METRIC_PERCENTILES.items():
        out[name] = float(np.percentile(values, q))
    out["max"] = float(values.max())
    return {k: round(v, SCORE_DECIMALS) for k, v in out.items()}
