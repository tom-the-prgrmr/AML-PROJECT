"""Score the anomaly alerts against the synthetic ground truth: what do they catch that rules miss?

Same measure as `network_coverage` of Phase 5c. The rules (RULE and NETWORK alerts in force) count
a scenario as caught when one of its accounts is in an alert, at any time. The model counts it
only when the owner of one of its accounts has an alerted customer-month that overlaps the time of
that ground-truth row. The comparison leans towards the rules on purpose, so ``new_by_anomaly`` is
a lower bound. Nothing is written.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from aml.cases.values import lower_columns, plain_date
from aml.common.config import Settings
from aml.common.db import Database
from aml.datagen.activity import TYPOLOGY_KEYS
from aml.ml.anomaly.runner import AnomalyError

COVERAGE_COLUMNS = [
    "typology", "is_suspicious", "scenarios", "flagged_rules", "flagged_anomaly", "flagged_any",
    "new_by_anomaly", "accounts", "accounts_rules", "accounts_anomaly", "accounts_new",
]  # fmt: skip
NO_RUN = "no anomaly run yet: run `aml anomaly run` first"
NO_TRUTH = "no ground truth: nothing to evaluate against"
SUSPICIOUS_TOTALS = [
    c for c in COVERAGE_COLUMNS if c not in ("typology", "is_suspicious", "flagged_any")
]
KINDS = ("suspicious", "benign", "scenario_other_month", "none")


def run_row(db: Database, run_id: int | None) -> pd.Series:
    where = (
        "run_id = (SELECT MAX(run_id) FROM anomaly_runs)"
        if run_id is None
        else (f"run_id = {int(run_id)}")
    )
    runs = lower_columns(db.query_df(f"SELECT * FROM anomaly_runs WHERE {where}"))
    if runs.empty:
        raise AnomalyError(NO_RUN if run_id is None else f"unknown anomaly run {run_id}")
    return runs.iloc[0]


def json_value(value: Any) -> Any:
    text = value.read() if hasattr(value, "read") else value
    return json.loads(text) if isinstance(text, str) else text


def _truth(db: Database) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The scenarios, and the ground-truth rows of kind account with the CIF that owns them."""
    if int(db.query_df("SELECT COUNT(*) FROM ground_truth").iloc[0, 0]) == 0:
        raise AnomalyError(NO_TRUTH)
    scenarios = lower_columns(
        db.query_df("SELECT DISTINCT scenario_id, typology, is_suspicious FROM ground_truth")
    )
    scenarios["is_suspicious"] = [bool(v) for v in scenarios["is_suspicious"]]
    rows = lower_columns(
        db.query_df(
            "SELECT g.scenario_id, g.entity_id AS account_id, g.start_ts, g.end_ts, a.cif "
            "FROM ground_truth g JOIN accounts a ON a.account_id = g.entity_id "
            "WHERE g.entity_type = 'account'"
        )
    )
    rows["start_ts"] = pd.to_datetime(rows["start_ts"])
    rows["end_ts"] = pd.to_datetime(rows["end_ts"])
    return scenarios, rows.merge(scenarios[["scenario_id", "is_suspicious"]], on="scenario_id")


def _rule_accounts(db: Database) -> pd.DataFrame:
    """Accounts (with owner) of the RULE and NETWORK alerts in force."""
    return lower_columns(
        db.query_df(
            "SELECT DISTINCT c.account_id, c.cif FROM alerts_current a "
            "JOIN alert_accounts c ON c.alert_id = a.alert_id "
            "WHERE a.source IN ('RULE', 'NETWORK')"
        )
    )


def _overlaps(pairs: pd.DataFrame) -> pd.Series:
    """True where the calendar month of a pair overlaps [start_ts, end_ts] of its truth row."""
    start = pd.to_datetime(pairs["month"] + "-01")
    following = start + pd.offsets.MonthBegin(1)
    return (start <= pairs["end_ts"]) & (following > pairs["start_ts"])  # NaT never overlaps


def _alerted(db: Database, run_id: int) -> pd.DataFrame:
    return lower_columns(
        db.query_df(
            f"SELECT cif, month FROM anomaly_scores WHERE run_id = {run_id} AND alerted = 1"
        )
    )


def _coverage_rows(
    scenarios: pd.DataFrame, rows: pd.DataFrame, flagged: pd.DataFrame, by_rules: set[str]
) -> pd.DataFrame:
    """One row per typology with scenarios; ``flagged`` holds the truth rows the model reached."""
    hit_accounts, hit_scenarios = set(flagged["account_id"]), set(flagged["scenario_id"])
    rule_scenarios = set(rows.loc[rows["account_id"].isin(by_rules), "scenario_id"])
    out = []
    for typology in TYPOLOGY_KEYS:
        mine = scenarios[scenarios["typology"] == typology]
        if mine.empty:
            continue
        ids = set(mine["scenario_id"])
        own = set(rows.loc[rows["scenario_id"].isin(ids), "account_id"])
        rules, anomaly = ids & rule_scenarios, ids & hit_scenarios
        in_rules, in_anomaly = own & by_rules, own & hit_accounts
        out.append(
            {
                "typology": typology,
                "is_suspicious": bool(mine["is_suspicious"].iloc[0]),
                "scenarios": len(ids),
                "flagged_rules": len(rules),
                "flagged_anomaly": len(anomaly),
                "flagged_any": len(rules | anomaly),
                "new_by_anomaly": len(anomaly - rules),
                "accounts": len(own),
                "accounts_rules": len(in_rules),
                "accounts_anomaly": len(in_anomaly),
                "accounts_new": len(in_anomaly - in_rules),
            }
        )
    return pd.DataFrame(out, columns=COVERAGE_COLUMNS)


def _reached(rows: pd.DataFrame, alerted: pd.DataFrame) -> pd.DataFrame:
    """The truth rows whose owner has an alerted customer-month overlapping the row's time."""
    pairs = rows.merge(alerted, on="cif")
    return pairs[_overlaps(pairs)]


def _alerts_by_kind(rows: pd.DataFrame, alerted: pd.DataFrame) -> dict[str, int]:
    """Each alert once, the first kind that fits: suspicious, benign, other month, none."""
    pairs = alerted.merge(rows, on="cif", how="left")
    pairs["overlap"] = _overlaps(pairs) & pairs["scenario_id"].notna()
    counts = dict.fromkeys(KINDS, 0)
    for _, g in pairs.groupby(["cif", "month"]):
        if (g["overlap"] & g["is_suspicious"].eq(True)).any():
            counts["suspicious"] += 1
        elif g["overlap"].any():
            counts["benign"] += 1
        elif g["scenario_id"].notna().any():
            counts["scenario_other_month"] += 1
        else:
            counts["none"] += 1
    return counts


def _total(coverage: pd.DataFrame, suspicious: bool, columns: list[str]) -> dict[str, int]:
    part = coverage[coverage["is_suspicious"] == suspicious]
    return {c: int(part[c].sum()) for c in columns}


def anomaly_coverage(db: Database) -> pd.DataFrame:
    """Per typology: scenarios and accounts the rules caught, the model caught, and the new ones."""
    run = run_row(db, None)
    scenarios, rows = _truth(db)
    reached = _reached(rows, _alerted(db, int(run["run_id"])))
    return _coverage_rows(scenarios, rows, reached, set(_rule_accounts(db)["account_id"]))


def evaluate_anomaly(
    db: Database, settings: Settings, *, run_id: int | None = None
) -> dict[str, Any]:
    """Summary and coverage of an anomaly run (the current one by default). Writes nothing."""
    run = run_row(db, run_id)
    scenarios, rows = _truth(db)
    alerted = _alerted(db, int(run["run_id"]))
    rules = _rule_accounts(db)
    coverage = _coverage_rows(scenarios, rows, _reached(rows, alerted), set(rules["account_id"]))
    config = json_value(run["params"]).get("config", {})
    return {
        "run_id": int(run["run_id"]),
        "model_version": str(run["model_version"]),
        "as_of": plain_date(run["as_of"]).isoformat(),
        "samples": int(run["samples"]),
        "alerts": int(run["alerts"]),
        "alert_top_fraction": float(
            config.get("alert_top_fraction", settings.ml.anomaly.alert_top_fraction)
        ),
        "threshold": float(run["threshold"]),
        "suspicious": _total(coverage, True, SUSPICIOUS_TOTALS),
        "benign": _total(coverage, False, ["scenarios", "flagged_anomaly", "accounts_anomaly"]),
        "alerts_by_kind": _alerts_by_kind(rows, alerted),
        "alerts_on_rule_alerted_customers": int(alerted["cif"].isin(set(rules["cif"])).sum()),
        "coverage": [
            {
                k: (bool(v) if k == "is_suspicious" else v if k == "typology" else int(v))
                for k, v in r.items()
            }
            for r in coverage.to_dict("records")
        ],
    }
