"""Compare two-tier screening with two naive baselines against the Phase 1 ground truth.

A flagged item is a (cif, entry_id) pair; the truth is every sanctions/PEP customer paired with
the watchlist entry planted for the same scenario. Synthetic data only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from aml.common.config import Settings
from aml.common.db import Database
from aml.screening.matching import ScreeningInputs, customer_norms, entry_names, load_inputs

Pair = tuple[str, str]
METHODS = ("exact", "fuzzy", "two_tier_alert", "two_tier")
COLUMNS = ["method", "flagged", "tp", "fp", "fn", "precision", "recall", "fp_reduction_pct"]
BLOCK = 2000  # customer names scored per cdist call, to bound memory


def truth_pairs(db: Database) -> frozenset[Pair]:
    """(cif, entry_id) pairs of the planted sanctions / PEP true hits."""
    df = db.query_df(
        "SELECT c.entity_id AS cif, w.entity_id AS entry_id "
        "FROM ground_truth c JOIN ground_truth w ON c.scenario_id = w.scenario_id "
        "WHERE c.entity_type = 'customer' AND w.entity_type = 'watchlist_entry' "
        "AND c.typology IN ('sanctions_hit', 'pep_hit') "
        "AND w.typology IN ('sanctions_hit', 'pep_hit')"
    )
    return frozenset(zip(df["cif"].astype(str), df["entry_id"].astype(str), strict=True))


def _expand(
    name_pairs: set[tuple[str, str]],
    customers: dict[str, list[str]],
    names: dict[str, list[tuple[str, str]]],
) -> set[Pair]:
    return {
        (cif, entry_id)
        for cust_name, list_name in name_pairs
        for cif in customers[cust_name]
        for entry_id, _ in names[list_name]
    }


def _exact_pairs(
    customers: dict[str, list[str]], names: dict[str, list[tuple[str, str]]]
) -> set[Pair]:
    return _expand({(n, n) for n in customers.keys() & names.keys()}, customers, names)


def _fuzzy_pairs(
    customers: dict[str, list[str]], names: dict[str, list[tuple[str, str]]], threshold: float
) -> set[Pair]:
    """Exhaustive token_set_ratio >= threshold. cdist is a coarse filter (float32, cutoff one
    point lower); every survivor is re-scored exactly so 89.6 is never rounded up to 90."""
    cust, listed = sorted(customers), sorted(names)
    hits: set[tuple[str, str]] = set()
    if not cust or not listed:
        return set()
    for start in range(0, len(cust), BLOCK):
        chunk = cust[start : start + BLOCK]
        scores = process.cdist(
            chunk, listed, scorer=fuzz.token_set_ratio, dtype=np.float32,
            score_cutoff=threshold - 1, workers=-1,
        )  # fmt: skip
        for i, j in zip(*np.nonzero(scores), strict=True):
            if fuzz.token_set_ratio(chunk[i], listed[j]) >= threshold:
                hits.add((chunk[i], listed[j]))
    return _expand(hits, customers, names)


def _row(method: str, flagged: set[Pair], truth: frozenset[Pair]) -> dict[str, object]:
    tp = len(flagged & truth)
    return {
        "method": method,
        "flagged": len(flagged),
        "tp": tp,
        "fp": len(flagged) - tp,
        "fn": len(truth) - tp,
        "precision": round(tp / len(flagged), 4) if flagged else 1.0,
        "recall": round(tp / len(truth), 4) if truth else 1.0,
    }


def current_pairs(db: Database, decisions: str) -> set[Pair]:
    df = db.query_df(f"SELECT cif, entry_id FROM screening_current WHERE decision IN ({decisions})")
    return set(zip(df["cif"].astype(str), df["entry_id"].astype(str), strict=True))


def evaluate(db: Database, settings: Settings) -> pd.DataFrame:
    """Four rows (exact, fuzzy, two_tier_alert, two_tier) scored against ``truth_pairs``."""
    cfg = settings.screening
    inputs: ScreeningInputs = load_inputs(db)
    customers, names = customer_norms(inputs, cfg), entry_names(inputs, cfg)
    truth = truth_pairs(db)
    flagged = {
        "exact": _exact_pairs(customers, names),
        "fuzzy": _fuzzy_pairs(customers, names, cfg.alert_threshold),
        "two_tier_alert": current_pairs(db, "'ALERT'"),
        "two_tier": current_pairs(db, "'ALERT', 'REVIEW'"),
    }
    rows = [_row(m, flagged[m], truth) for m in METHODS]
    baseline_fp = rows[1]["fp"]
    for row in rows:
        row["fp_reduction_pct"] = (
            None if not baseline_fp else round(100 * (1 - row["fp"] / baseline_fp), 2)  # type: ignore[operator]
        )
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["fp_reduction_pct"] = (
        df["fp_reduction_pct"].astype(object).where(df["fp_reduction_pct"].notna(), None)
    )
    return df
