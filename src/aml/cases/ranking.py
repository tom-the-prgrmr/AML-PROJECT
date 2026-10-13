"""Ranking metrics of a case queue: how well a score puts the suspicious cases first.

Pure functions of a label series and a score series. The order is score descending; a tie goes to
the smaller index value (the case id), so two runs on the same data give the same numbers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

__all__ = ["ranking_metrics", "slice_size"]


def slice_size(fraction: float, n: int) -> int:
    """``ceil(fraction * n)`` cases, at least 1 and at most ``n`` (rounded first: 0.7 * 10 is 7)."""
    return min(n, max(1, math.ceil(round(fraction * n, 9)))) if n else 0


def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 4)


def ranked_labels(y: pd.Series, score: pd.Series) -> np.ndarray:
    """Labels (0 / 1) in queue order: score descending, then index ascending."""
    by_index = np.argsort(y.index.to_numpy(), kind="stable")
    labels = y.to_numpy()[by_index].astype(int)
    scores = score.reindex(y.index).to_numpy(dtype=float)[by_index]
    return labels[np.argsort(-scores, kind="stable")]


def ranking_metrics(y: pd.Series, score: pd.Series, fractions: Sequence[float]) -> dict[str, Any]:
    """Prevalence, ROC-AUC, PR-AUC and head / tail counts of the queue ordered by ``score``.

    ``y`` is 1 for SUSPICIOUS and 0 for FALSE_POSITIVE. The head of a fraction ``f`` is the first
    ``ceil(f * n)`` cases, the tail the last ``ceil(f * n)``. ``roc_auc`` and ``pr_auc`` are None
    when only one class is present; a ratio with a zero denominator is None. Reals are rounded to 4.
    """
    from sklearn.metrics import average_precision_score, roc_auc_score

    n = len(y)
    ordered = ranked_labels(y, score)
    positives = int(ordered.sum())
    negatives = n - positives
    both = positives > 0 and negatives > 0
    precision: dict[float, float | None] = {}
    recall: dict[float, float | None] = {}
    tail_share: dict[float, float | None] = {}
    tail_suspicious: dict[float, int] = {}
    for f in fractions:
        k = slice_size(f, n)
        head_hits = int(ordered[:k].sum())
        tail_hits = int(ordered[n - k :].sum())
        precision[f] = _ratio(head_hits, k)
        recall[f] = _ratio(head_hits, positives)
        tail_share[f] = _ratio(k - tail_hits, negatives)
        tail_suspicious[f] = tail_hits
    scores = score.reindex(y.index).to_numpy(dtype=float)
    return {
        "n": n,
        "n_suspicious": positives,
        "n_false_positive": negatives,
        "prevalence": _ratio(positives, n),
        "roc_auc": round(float(roc_auc_score(y.to_numpy(), scores)), 4) if both else None,
        "pr_auc": round(float(average_precision_score(y.to_numpy(), scores)), 4) if both else None,
        "precision_at": precision,
        "recall_at": recall,
        "tail_false_positive_share": tail_share,
        "tail_suspicious": tail_suspicious,
    }
