"""The facts a model card needs about the anomaly model, as a plain dict.

The card format belongs to the governance spec; this module only collects what the run tables
already hold, so every figure in a card traces back to a stored run.
"""

from __future__ import annotations

from typing import Any

from aml.cases.values import lower_columns, plain_date
from aml.common.config import Settings
from aml.common.db import Database
from aml.ml.anomaly.evaluate import NO_TRUTH, evaluate_anomaly, json_value, run_row
from aml.ml.anomaly.features import ANOMALY_FEATURES, FEATURE_DOCS
from aml.ml.anomaly.runner import AnomalyError

__all__ = ["LIMITATIONS", "card_facts"]

LIMITATIONS = (
    "All data is synthetic: the scores say how unusual a customer-month is among its peers in the "
    "generated data, not how a real customer base behaves.",
    "The four graph features are one snapshot of the last network / GDS run shared by every "
    "month, so older months see information from after they happened (temporal leakage).",
    "No night-time signal is planted in the synthetic data (every planted typology happens in "
    "daylight), so night_ratio is expected to add almost nothing.",
    "Merchant-like benign customers (many counterparties, large flows) score high: expect false "
    "positives that no rule produces.",
    "The threshold is a fraction of the samples, so every run raises exactly that many alerts, "
    "even when nothing is unusual.",
    "ANOMALY items also enter the pinned case features alerts, distinct_rules and "
    "alert_amount_log (the anomaly alert carries the whole month, so money already in RULE "
    "alerts is counted twice); with ml.anomaly.features=off the case scores of cases holding an "
    "ANOMALY item still change.",
    "On this synthetic data the rules already catch every suspicious scenario, so the number of "
    "scenarios only the model catches is expected to be zero; the model's value is as a ranking "
    "feature and as a second opinion.",
)


def _month_bounds(db: Database, run_id: int) -> tuple[str, str]:
    df = lower_columns(
        db.query_df(
            f"SELECT MIN(month) AS first_month, MAX(month) AS last_month "
            f"FROM anomaly_scores WHERE run_id = {run_id}"
        )
    )
    return str(df["first_month"].iloc[0]), str(df["last_month"].iloc[0])


def card_facts(db: Database, settings: Settings, run_id: int | None = None) -> dict[str, Any]:
    """Facts of one anomaly run (the newest by default); raises `AnomalyError` when none exists."""
    run = run_row(db, run_id)
    params = json_value(run["params"])
    first_month, last_month = _month_bounds(db, int(run["run_id"]))
    try:
        evaluation = evaluate_anomaly(db, settings, run_id=int(run["run_id"]))
    except AnomalyError as exc:
        if str(exc) != NO_TRUTH:
            raise
        evaluation = None
    return {
        "model": {
            "name": "ml-anomaly",
            "kind": str(run["kind"]),
            "version": str(run["model_version"]),
            "feature_version": str(run["feature_version"]),
            "trained_ts": str(run["run_ts"]),
            "as_of": plain_date(run["as_of"]).isoformat(),
            "seed": int(run["seed"]),
            "sklearn_version": params.get("sklearn_version"),
        },
        "data": {
            "synthetic": True,
            "samples": int(run["samples"]),
            "customers": int(run["customers"]),
            "months": int(run["months"]),
            "first_month": first_month,
            "last_month": last_month,
            "graph_source": str(run["graph_source"]),
            "data_hash": str(run["data_hash"]),
        },
        "features": [{"name": name, "doc": FEATURE_DOCS[name]} for name in ANOMALY_FEATURES],
        "params": params,
        "metrics": json_value(run["metrics"]),
        "alerts": {
            "count": int(run["alerts"]),
            "top_fraction": params.get("config", {}).get(
                "alert_top_fraction", settings.ml.anomaly.alert_top_fraction
            ),
            "threshold": float(run["threshold"]),
        },
        "evaluation": evaluation,
        "limitations": LIMITATIONS,
        "use": {"purpose": "alert source and ranking feature", "auto_close": False},
    }
