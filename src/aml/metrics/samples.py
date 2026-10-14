"""Below-the-line samples: auto-cleared screening hits and suppressed alert items."""

from __future__ import annotations

from typing import Any

import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database
from aml.metrics.common import clean, latest_run, read, sample_indices, sql
from aml.metrics.funnel import suppression_stage
from aml.screening.evaluate import truth_pairs

RULES = ("GOOD_GUY", "HIBERNATION")


def _has_truth(db: Database) -> bool:
    return int(read(db, "ground_truth_rows.sql").iloc[0]["n"]) > 0


def auto_cleared_sample(
    db: Database, settings: Settings, *, size: int | None = None
) -> dict[str, Any]:
    population = read(db, "auto_cleared.sql")
    available = _has_truth(db)
    truth = truth_pairs(db) if available else frozenset()
    pairs = list(
        zip(population["cif"].astype(str), population["entry_id"].astype(str), strict=True)
    )
    hits = [pair in truth for pair in pairs]
    picks = sample_indices(settings, len(pairs), size)
    sample = []
    for i in picks:
        rec = population.iloc[i]
        sample.append(
            {
                "cif": pairs[i][0],
                "entry_id": pairs[i][1],
                "list_type": clean(rec["list_type"]),
                "final_score": clean(rec["final_score"]),
                "reason": clean(rec["reason"]),
                "truth": ("TRUE_HIT" if hits[i] else "NOT_A_HIT") if available else None,
            }
        )
    return {
        "population": len(pairs),
        "ground_truth_available": available,
        "true_hits_in_population": sum(hits) if available else None,
        "seed": settings.seed,
        "sample_size": len(picks),
        "true_hits_in_sample": sum(hits[i] for i in picks) if available else None,
        "sample": sample,
    }


def _suspicious_items(db: Database, run_id: int) -> set[tuple[str, str]]:
    """(item_key, golden_customer_id) of suppressed rule / network items on a scenario account."""
    text = sql(db, "suppressed_truth_accounts.sql").replace("{run_id}", str(int(run_id)))
    df = db.query_df(text)
    df.columns = [str(c).lower() for c in df.columns]
    return {
        (str(k), str(g))
        for k, g, s in zip(
            df["item_key"], df["golden_customer_id"], df["is_suspicious"], strict=True
        )
        if bool(s)
    }


def _item_truths(db: Database, population: pd.DataFrame, run_id: int) -> list[str]:
    pairs = truth_pairs(db)
    bad = _suspicious_items(db, run_id)
    out = []
    for rec in population.to_dict("records"):
        if rec["source"] == "SCREENING":
            hit = (str(rec["cif"]), str(rec["entry_id"])) in pairs
        else:
            hit = (str(rec["item_key"]), str(rec["golden_customer_id"])) in bad
        out.append("SUSPICIOUS" if hit else "NOT_SUSPICIOUS")
    return out


def suppression(db: Database, settings: Settings, *, size: int | None = None) -> dict[str, Any]:
    run = latest_run(db)
    stage_, unavailable = suppression_stage(settings, run)
    base: dict[str, Any] = {
        "case_run": None if run is None else {"run_id": run["run_id"], "as_of": run["as_of"]},
        "minutes_per_alert": settings.metrics.minutes_per_alert,
        "stage": stage_,
        "seed": settings.seed,
        "unavailable": unavailable,
    }
    available = _has_truth(db)
    if run is None:
        return {
            **base,
            "by_rule": None,
            "population": 0,
            "ground_truth_available": available,
            "suspicious_suppressed": None,
            "sample_size": 0,
            "sample": [],
        }
    population = read(db, "suppressed.sql")
    truths = _item_truths(db, population, run["run_id"]) if available else []
    picks = sample_indices(settings, len(population), size)
    keys = ("item_key", "golden_customer_id", "source", "rule_id")
    sample = []
    for i in picks:
        rec = population.iloc[i]
        sample.append(
            {
                **{k: clean(rec[k]) for k in keys},
                "suppression_rule": clean(rec["suppression_rule"]),
                "suppression_reason": clean(rec["suppression_reason"]),
                "truth": truths[i] if available else None,
            }
        )
    return {
        **base,
        "by_rule": {r: int((population["suppression_rule"] == r).sum()) for r in RULES},
        "population": len(population),
        "ground_truth_available": available,
        "suspicious_suppressed": truths.count("SUSPICIOUS") if available else None,
        "sample_size": len(picks),
        "sample": sample,
    }
