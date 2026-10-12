"""Network detections: shared attributes, cycles and hubs over one read of the data.

`detect_network` computes everything in memory and writes nothing; storing the result is
`run_network` (next to it, through ``aml.monitoring.recording.record_run``).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.network.cycles import detect_cycles
from aml.graph.network.hubs import detect_hubs
from aml.graph.network.inputs import NetworkError, read_inputs
from aml.graph.network.rules import NETWORK_RULES, network_rule_params
from aml.graph.network.shared import detect_shared
from aml.monitoring.recording import AlertRecord, RuleRun, record_run

__all__ = [
    "FEATURE_COLUMNS",
    "NetworkDetections",
    "NetworkError",
    "NetworkRun",
    "detect_network",
    "run_network",
]

SOURCE_NETWORK = "NETWORK"

FEATURE_COLUMNS = [
    "account_id",
    "in_degree",
    "out_degree",
    "in_vnd",
    "out_vnd",
    "pagerank",
    "pagerank_ratio",
    "cycle_alerts",
    "shared_cluster_id",
    "shared_cluster_size",
    "is_hub",
]


@dataclass(frozen=True)
class NetworkDetections:
    alerts: tuple[AlertRecord, ...]  # shared attribute, then cycles, then hubs
    features: pd.DataFrame  # FEATURE_COLUMNS, one row per account, sorted by account_id
    active_accounts: int  # accounts with at least one edge in the hub graph
    cycle_search_steps: int


@dataclass(frozen=True)
class NetworkRun:
    run_id: int
    as_of: date
    alerts: int
    evidence: int  # alert_evidence rows of the run
    by_rule: dict[str, int]  # all three rules, zeros included
    accounts: int  # nx_account_features rows of the run
    active_accounts: int
    cycle_search_steps: int


def detect_network(
    db: Database, settings: Settings, *, as_of: date | None = None
) -> NetworkDetections:
    """Run the three detections as of ``as_of`` (default: the reference date); no writes."""
    cfg = settings.network
    inputs = read_inputs(db, as_of or settings.data.reference_date)
    shared = detect_shared(inputs, cfg.shared_attributes)
    cycles = detect_cycles(inputs.transfers, inputs.owner, cfg.cycles)
    hubs = detect_hubs(inputs, cfg.hubs)

    in_cycle = Counter(a for alert in cycles.alerts for a, _ in alert.accounts)
    hub_ids = {alert.subject_id for alert in hubs.alerts}
    features = hubs.features.copy()
    ids = list(features["account_id"])
    features["cycle_alerts"] = [in_cycle.get(a, 0) for a in ids]
    features["shared_cluster_id"] = pd.Series(
        [shared.cluster_of.get(a, (None, 0))[0] for a in ids], dtype=object
    )
    features["shared_cluster_size"] = [shared.cluster_of.get(a, (None, 0))[1] for a in ids]
    features["is_hub"] = [int(a in hub_ids) for a in ids]
    return NetworkDetections(
        (*shared.alerts, *cycles.alerts, *hubs.alerts),
        features[FEATURE_COLUMNS],
        hubs.active_accounts,
        cycles.steps,
    )


_INT_FEATURES = [
    "in_degree", "out_degree", "in_vnd", "out_vnd", "cycle_alerts", "shared_cluster_size", "is_hub",
]  # fmt: skip
_FLOAT_FEATURES = ["pagerank", "pagerank_ratio"]


def _feature_rows(run_id: int, features: pd.DataFrame) -> pd.DataFrame:
    """Typed columns for the insert; ``shared_cluster_id`` keeps None for "no cluster".

    Object columns would make DuckDB guess the type from a sample of rows and then fail on a
    later VND total above the 32-bit range.
    """
    rows = features.astype(
        dict.fromkeys(_INT_FEATURES, "int64") | dict.fromkeys(_FLOAT_FEATURES, "float64")
    )
    rows["shared_cluster_id"] = (
        rows["shared_cluster_id"].astype(object).where(rows["shared_cluster_id"].notna(), None)
    )
    rows.insert(0, "run_id", run_id)
    return rows


def run_network(db: Database, settings: Settings, *, as_of: date | None = None) -> NetworkRun:
    """Detect, store the alerts through ``record_run`` and then the per-account features.

    Every failure (missing data, search budget) is raised by ``detect_network`` before the
    first write, so an error leaves nothing behind.
    """
    as_of = as_of or settings.data.reference_date
    found = detect_network(db, settings, as_of=as_of)
    rules = [
        RuleRun(r.rule_id, r.rule_version, network_rule_params(r.rule_id, settings))
        for r in NETWORK_RULES
    ]
    run_id = record_run(db, as_of=as_of, source=SOURCE_NETWORK, rules=rules, alerts=found.alerts)
    db.insert_df("nx_account_features", _feature_rows(run_id, found.features))
    return NetworkRun(
        run_id=run_id,
        as_of=as_of,
        alerts=len(found.alerts),
        evidence=sum(len(a.txn_ids) for a in found.alerts),
        by_rule={
            r.rule_id: sum(a.rule_id == r.rule_id for a in found.alerts) for r in NETWORK_RULES
        },
        accounts=len(found.features),
        active_accounts=found.active_accounts,
        cycle_search_steps=found.cycle_search_steps,
    )
