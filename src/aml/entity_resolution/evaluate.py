"""Pairwise and cluster precision/recall of the current run against the Phase 1 ground truth.

The truth is ``customer_person`` (cif -> person_id); a CIF without a row there counts as its own
person. Only the CIFs of the current run are evaluated. Synthetic data only.
"""

from __future__ import annotations

from itertools import combinations

import pandas as pd

from aml.common.db import Database
from aml.entity_resolution.runner import ErError

COLUMNS = ["level", "predicted", "truth", "tp", "fp", "fn", "precision", "recall"]
Group = frozenset[str]


def _groups(df: pd.DataFrame, key: str) -> set[Group]:
    """CIF sets sharing the same ``key`` value, keeping only sets of two or more."""
    return {frozenset(g["cif"]) for _, g in df.groupby(key) if len(g) > 1}


def _pairs(groups: set[Group]) -> set[tuple[str, str]]:
    return {pair for group in groups for pair in combinations(sorted(group), 2)}


def _row(level: str, predicted: set, truth: set) -> dict[str, object]:
    tp = len(predicted & truth)
    return {
        "level": level,
        "predicted": len(predicted),
        "truth": len(truth),
        "tp": tp,
        "fp": len(predicted) - tp,
        "fn": len(truth) - tp,
        "precision": round(tp / len(predicted), 4) if predicted else 1.0,
        "recall": round(tp / len(truth), 4) if truth else 1.0,
    }


def evaluate_er(db: Database) -> pd.DataFrame:
    """Two rows: ``pairwise`` (same-golden-id pairs) and ``cluster`` (exact CIF-set match)."""
    df = db.query_df(
        "SELECT g.cif, g.golden_customer_id, p.person_id "
        "FROM customer_golden g LEFT JOIN customer_person p ON p.cif = g.cif"
    )
    if df.empty:
        raise ErError("no entity-resolution run found; run `aml er` first")
    df["person_id"] = df["person_id"].where(df["person_id"].notna(), "cif:" + df["cif"])
    predicted, truth = _groups(df, "golden_customer_id"), _groups(df, "person_id")
    rows = [
        _row("pairwise", _pairs(predicted), _pairs(truth)),
        _row("cluster", predicted, truth),
    ]
    return pd.DataFrame(rows, columns=COLUMNS)
