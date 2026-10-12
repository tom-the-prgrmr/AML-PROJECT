"""Score the current network alerts against the Phase 1 ground truth (synthetic data only).

A network alert covers several accounts, so it is matched to a scenario through its accounts:
the scenario holding most of them (ties: the smaller scenario id). `network_coverage` also
shows what the network adds on top of the current rule alerts of Phase 5a.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from aml.common.db import Database
from aml.datagen.activity import TYPOLOGY_KEYS
from aml.graph.network.inputs import NetworkError
from aml.graph.network.rules import NETWORK_RULES
from aml.monitoring.evaluate import EVAL_COLUMNS

COVERAGE_COLUMNS = [
    "typology", "is_suspicious", "scenarios", "flagged_rule", "flagged_network", "flagged_any",
    "new_by_network", "accounts", "accounts_rule", "accounts_network", "accounts_any",
    "accounts_new", "rules",
]  # fmt: skip


def _lower(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).lower() for c in df.columns]
    return df


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 4)


def _check_network_run(db: Database) -> None:
    n = int(db.query_df("SELECT COUNT(*) FROM monitoring_runs WHERE source = 'NETWORK'").iloc[0, 0])
    if n == 0:
        raise NetworkError("no network run yet; run `aml network` first")


def _scenarios(db: Database) -> pd.DataFrame:
    df = _lower(
        db.query_df("SELECT DISTINCT scenario_id, typology, is_suspicious FROM ground_truth")
    )
    df["is_suspicious"] = [bool(v) for v in df["is_suspicious"]]
    return df.sort_values("scenario_id").reset_index(drop=True)


def _scenario_of_account(db: Database) -> dict[str, str]:
    df = _lower(
        db.query_df(
            "SELECT DISTINCT entity_id, scenario_id FROM ground_truth WHERE entity_type = 'account'"
        )
    ).drop_duplicates("entity_id")
    return dict(zip(df["entity_id"], df["scenario_id"], strict=True))


def _current_alerts(db: Database) -> pd.DataFrame:
    """Current alerts, one row per (alert, account): alert_id, source, rule_id, account_id."""
    return _lower(
        db.query_df(
            "SELECT a.alert_id, a.source, a.rule_id, c.account_id FROM alerts_current a "
            "LEFT JOIN alert_accounts c ON c.alert_id = a.alert_id"
        )
    )


def _main_scenario(accounts: list[str], scenario_of: dict[str, str]) -> str | None:
    counts = Counter(scenario_of[a] for a in accounts if a in scenario_of)
    if not counts:
        return None
    return min(counts, key=lambda s: (-counts[s], s))


def evaluate_network(db: Database) -> pd.DataFrame:
    """Per network rule: where its current alerts land, in the columns of ``evaluate_rules``."""
    _check_network_run(db)
    scenarios = _scenarios(db).set_index("scenario_id")
    scenario_of = _scenario_of_account(db)
    alerts = _current_alerts(db)
    alerts = alerts[alerts["source"] == "NETWORK"]
    rows: list[dict[str, object]] = []
    for rule in NETWORK_RULES:
        mine = alerts[alerts["rule_id"] == rule.rule_id]
        found = [
            _main_scenario([a for a in group["account_id"] if isinstance(a, str)], scenario_of)
            for _, group in mine.groupby("alert_id", sort=True)
        ]
        kinds = ["unlabelled" if s is None else scenarios.loc[s, "typology"] for s in found]
        suspicious = [s is not None and bool(scenarios.loc[s, "is_suspicious"]) for s in found]
        target = rule.target_typology
        hits = sum(k == target for k in kinds)
        other = sum(sus and k != target for k, sus in zip(kinds, suspicious, strict=True))
        benign = sum(
            k != "unlabelled" and not sus for k, sus in zip(kinds, suspicious, strict=True)
        )
        n = len(found)
        total = int((scenarios["typology"] == target).sum())
        detected = {s for s, k in zip(found, kinds, strict=True) if k == target}
        rows.append(
            {
                "rule_id": rule.rule_id,
                "target_typology": target,
                "alerts": n,
                "target_hits": hits,
                "other_suspicious": other,
                "benign": benign,
                "unlabelled": sum(k == "unlabelled" for k in kinds),
                "precision": _ratio(hits, n),
                "precision_suspicious": _ratio(hits + other, n),
                "scenarios": total,
                "detected": len(detected),
                "recall": _ratio(len(detected), total),
            }
        )
    return pd.DataFrame(rows, columns=EVAL_COLUMNS).astype(object)


def network_coverage(db: Database) -> pd.DataFrame:
    """Per typology: scenarios and accounts flagged by the rules, by the network, and by either."""
    _check_network_run(db)
    scenarios = _scenarios(db)
    scenario_of = _scenario_of_account(db)
    alerts = _current_alerts(db).dropna(subset=["account_id"])
    rule_accounts = set(alerts.loc[alerts["source"] == "RULE", "account_id"])
    net = alerts[alerts["source"] == "NETWORK"]
    net_accounts = set(net["account_id"])
    rows: list[dict[str, object]] = []
    for typology in TYPOLOGY_KEYS:
        mine = scenarios[scenarios["typology"] == typology]
        if mine.empty:
            continue
        ids = set(mine["scenario_id"])
        own = {a for a, s in scenario_of.items() if s in ids}

        def flagged(accounts: set[str], own: set[str] = own) -> set[str]:
            return {scenario_of[a] for a in accounts & own}

        by_rule, by_net = flagged(rule_accounts), flagged(net_accounts)
        in_rule, in_net = own & rule_accounts, own & net_accounts
        rules = sorted(set(net.loc[net["account_id"].isin(own), "rule_id"]))
        rows.append(
            {
                "typology": typology,
                "is_suspicious": bool(mine["is_suspicious"].iloc[0]),
                "scenarios": len(mine),
                "flagged_rule": len(by_rule),
                "flagged_network": len(by_net),
                "flagged_any": len(by_rule | by_net),
                "new_by_network": len(by_net - by_rule),
                "accounts": len(own),
                "accounts_rule": len(in_rule),
                "accounts_network": len(in_net),
                "accounts_any": len(in_rule | in_net),
                "accounts_new": len(in_net - in_rule),
                "rules": ",".join(rules),  # built here: '' is NULL on Oracle
            }
        )
    return pd.DataFrame(rows, columns=COVERAGE_COLUMNS)
