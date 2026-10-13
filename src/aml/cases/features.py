"""The features of a case: a pure function of its stored alerts and enrichment.

`case_features` reads one `CaseView` (the snapshot a case run stored), so the same snapshot always
gives the same numbers. Nothing here reads a source table or labels. `write_features` stores the
values long (one row per case and feature) once per case run; a stored snapshot is never recomputed.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from aml.cases.model import PrioritizationError
from aml.cases.values import lower_columns
from aml.cases.view import CaseAlert, CaseView, load_case
from aml.common.db import Database

FEATURE_VERSION = "features/v1"

FEATURES: tuple[str, ...] = (
    "alerts", "rule_alerts", "network_alerts", "screening_alerts", "distinct_rules",
    "has_structuring", "has_rapid_movement", "has_high_velocity", "has_fan_in", "has_fan_out",
    "has_dormant_reactivation", "has_net_shared_attribute", "has_net_cycle", "has_net_hub",
    "has_screening_alert", "has_screening_review", "has_sanctions_hit", "max_screening_score",
    "alert_amount_log",
    "kyc_risk_level", "cifs", "accounts", "dq_issues",
    "txn_count", "in_vnd_log", "out_vnd_log", "cash_share", "counterparties", "pass_through",
    "in_degree", "out_degree", "pagerank_ratio", "shared_cluster_size",
    "prior_cases", "prior_false_positives",
)  # fmt: skip

_RULE_FLAGS = {
    "has_structuring": "STRUCTURING",
    "has_rapid_movement": "RAPID_MOVEMENT",
    "has_high_velocity": "HIGH_VELOCITY",
    "has_fan_in": "FAN_IN",
    "has_fan_out": "FAN_OUT",
    "has_dormant_reactivation": "DORMANT_REACTIVATION",
    "has_net_shared_attribute": "NET_SHARED_ATTRIBUTE",
    "has_net_cycle": "NET_CYCLE",
    "has_net_hub": "NET_HUB",
}
_KYC_LEVEL = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
DECIMALS = 10  # stored values are rounded, so both backends hold the same number


def _num(value: Any) -> float:
    """A finite float; NULL, a non-number or a non-finite value counts as 0."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _ratio(num: float, den: float) -> float:
    return num / den if den > 0 else 0.0


def _log(value: float) -> float:
    return math.log10(1 + max(value, 0.0))


def _alert_features(alerts: tuple[CaseAlert, ...]) -> dict[str, float]:
    rules = {a.rule_id for a in alerts}
    screening = [a for a in alerts if a.source == "SCREENING"]
    out = {
        "alerts": len(alerts),
        "rule_alerts": sum(a.source == "RULE" for a in alerts),
        "network_alerts": sum(a.source == "NETWORK" for a in alerts),
        "screening_alerts": len(screening),
        "distinct_rules": len(rules),
        "has_screening_alert": bool(screening),
        "has_screening_review": "SCREENING_REVIEW" in rules,
        "has_sanctions_hit": any(a.details.get("list_type") == "SANCTIONS" for a in screening),
        "max_screening_score": max(
            (_num(a.details.get("final_score")) for a in screening), default=0
        ),
        "alert_amount_log": _log(sum(a.amount_vnd for a in alerts)),
    }
    out |= {name: rule in rules for name, rule in _RULE_FLAGS.items()}
    return {k: _num(v) for k, v in out.items()}


def _enrichment_features(enrichment: dict[str, dict[str, Any]]) -> dict[str, float]:
    kyc, linked = enrichment.get("kyc", {}), enrichment.get("linked_cifs", {})
    txn, history = enrichment.get("txn_summary", {}), enrichment.get("history", {})
    graph = enrichment.get("network", {}).get("features") or {}
    money_in, money_out = _num(txn.get("in_vnd")), _num(txn.get("out_vnd"))
    cash = _num(txn.get("cash_in_vnd")) + _num(txn.get("cash_out_vnd"))
    prior = history.get("prior_cases") or []
    return {
        "kyc_risk_level": _KYC_LEVEL.get(str(kyc.get("risk_rating")), 0),
        "cifs": len(linked.get("cifs") or []),
        "accounts": len(linked.get("accounts") or []),
        "dq_issues": len(enrichment.get("dq_issues", {}).get("customer") or []),
        "txn_count": _num(txn.get("txn_count")),
        "in_vnd_log": _log(money_in),
        "out_vnd_log": _log(money_out),
        "cash_share": _ratio(cash, money_in + money_out),
        "counterparties": _num(txn.get("counterparties")),
        "pass_through": _ratio(min(money_in, money_out), max(money_in, money_out)),
        "in_degree": _num(graph.get("in_degree")),
        "out_degree": _num(graph.get("out_degree")),
        "pagerank_ratio": _num(graph.get("pagerank_ratio")),
        "shared_cluster_size": _num(graph.get("shared_cluster_size")),
        "prior_cases": len(prior),
        "prior_false_positives": sum(p.get("disposition") == "FALSE_POSITIVE" for p in prior),
    }


def case_features(view: CaseView) -> dict[str, float]:
    """All `FEATURES` of a case as finite floats (NULL counts as 0, a zero denominator as 0)."""
    values = _alert_features(view.alerts) | _enrichment_features(view.enrichment)
    return {name: _num(values[name]) for name in FEATURES}


def write_features(db: Database, run_id: int) -> int:
    """Store the features of every case of a run; 0 when the run already has rows.

    A snapshot is written once and never recomputed, so later decisions do not change the
    numbers a past disposition was made on.
    """
    if int(db.query_df(f"SELECT COUNT(*) FROM case_features WHERE run_id = {run_id}").iloc[0, 0]):
        return 0
    cases = lower_columns(db.query_df(f"SELECT case_id FROM cases WHERE run_id = {run_id}"))
    rows = [
        {"run_id": run_id, "case_id": case_id, "feature": name, "value": round(value, DECIMALS)}
        for case_id in sorted(str(c) for c in cases["case_id"])
        for name, value in case_features(
            load_case(db, case_id, run_id=run_id, scored=False)
        ).items()
    ]
    return db.insert_df("case_features", pd.DataFrame(rows)) if rows else 0


def read_features(db: Database, run_id: int) -> pd.DataFrame:
    """Stored features of a run: index ``case_id`` ascending, columns in `FEATURES` order."""
    df = lower_columns(
        db.query_df(f"SELECT case_id, feature, value FROM case_features WHERE run_id = {run_id}")
    )
    wide = df.pivot(index="case_id", columns="feature", values="value").astype(float)
    wide = wide.reindex(columns=list(FEATURES))
    if wide.isna().any().any():
        raise PrioritizationError(f"case_features of run {run_id} is incomplete: rerun the cases")
    return wide.loc[sorted(wide.index)].rename_axis("case_id")
