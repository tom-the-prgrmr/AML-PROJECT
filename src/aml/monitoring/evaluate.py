"""Score the current rule alerts against the Phase 1 ground truth (synthetic data only)."""

from __future__ import annotations

import pandas as pd

from aml.common.db import Database
from aml.datagen.activity import TYPOLOGY_KEYS
from aml.monitoring.rules import RULES

EVAL_COLUMNS = [
    "rule_id", "target_typology", "alerts", "target_hits", "other_suspicious", "benign",
    "unlabelled", "precision", "precision_suspicious", "scenarios", "detected", "recall",
]  # fmt: skip
COVERAGE_COLUMNS = ["typology", "is_suspicious", "scenarios", "flagged", "rate", "rules"]


def _lower(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).lower() for c in df.columns]
    return df


def _scenarios(db: Database) -> pd.DataFrame:
    """One row per ground-truth scenario: scenario_id, typology, is_suspicious."""
    df = _lower(
        db.query_df("SELECT DISTINCT scenario_id, typology, is_suspicious FROM ground_truth")
    )
    df["is_suspicious"] = [bool(v) for v in df["is_suspicious"]]
    return df


def _alerts_with_scenario(db: Database) -> pd.DataFrame:
    """Current RULE alerts: rule_id, scenario_id (None when the subject is in no scenario)."""
    alerts = _lower(
        db.query_df(
            "SELECT alert_id, rule_id, subject_id FROM alerts_current WHERE source = 'RULE'"
        )
    )
    accounts = _lower(
        db.query_df(
            "SELECT DISTINCT entity_id, scenario_id FROM ground_truth WHERE entity_type = 'account'"
        )
    ).drop_duplicates("entity_id")
    merged = alerts.merge(accounts, how="left", left_on="subject_id", right_on="entity_id")
    merged["scenario_id"] = (
        merged["scenario_id"].astype(object).where(merged["scenario_id"].notna(), None)
    )
    return merged[["alert_id", "rule_id", "scenario_id"]]


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 4)


def evaluate_rules(db: Database) -> pd.DataFrame:
    """Per rule: where its current alerts land (target / other suspicious / benign / unlabelled)."""
    scenarios = _scenarios(db).set_index("scenario_id")
    alerts = _alerts_with_scenario(db)
    rows: list[dict[str, object]] = []
    for rule in RULES:
        mine = alerts[alerts["rule_id"] == rule.rule_id]
        kinds = [
            "unlabelled" if s is None else scenarios.loc[s, "typology"] for s in mine["scenario_id"]
        ]
        suspicious = [
            s is not None and bool(scenarios.loc[s, "is_suspicious"]) for s in mine["scenario_id"]
        ]
        target = rule.target_typology
        hits = sum(k == target for k in kinds) if target else None
        other = sum(sus and k != target for k, sus in zip(kinds, suspicious, strict=True))
        benign = sum(
            k != "unlabelled" and not sus for k, sus in zip(kinds, suspicious, strict=True)
        )
        unlabelled = sum(k == "unlabelled" for k in kinds)
        n = len(mine)
        row: dict[str, object] = {
            "rule_id": rule.rule_id,
            "target_typology": target,
            "alerts": n,
            "target_hits": hits,
            "other_suspicious": other,
            "benign": benign,
            "unlabelled": unlabelled,
            "precision": None if hits is None else _ratio(hits, n),
            "precision_suspicious": _ratio((hits or 0) + other, n),
            "scenarios": None,
            "detected": None,
            "recall": None,
        }
        if target:
            total = int((scenarios["typology"] == target).sum())
            found = {s for s, k in zip(mine["scenario_id"], kinds, strict=True) if k == target}
            row.update(scenarios=total, detected=len(found), recall=_ratio(len(found), total))
        rows.append(row)
    return pd.DataFrame(rows, columns=EVAL_COLUMNS).astype(object)


def typology_coverage(db: Database) -> pd.DataFrame:
    """Per typology: how many scenarios at least one rule flagged, and which rules did."""
    scenarios = _scenarios(db)
    alerts = _alerts_with_scenario(db).dropna(subset=["scenario_id"])
    rows: list[dict[str, object]] = []
    for typology in TYPOLOGY_KEYS:
        mine = scenarios[scenarios["typology"] == typology]
        if mine.empty:
            continue
        hit = alerts[alerts["scenario_id"].isin(set(mine["scenario_id"]))]
        flagged = int(hit["scenario_id"].nunique())
        rows.append(
            {
                "typology": typology,
                "is_suspicious": bool(mine["is_suspicious"].iloc[0]),
                "scenarios": len(mine),
                "flagged": flagged,
                "rate": round(flagged / len(mine), 4),
                "rules": ",".join(sorted(set(hit["rule_id"]))),  # built here: '' is NULL on Oracle
            }
        )
    return pd.DataFrame(rows, columns=COVERAGE_COLUMNS)
