"""NET_HUB: accounts that collect money from many other customers, ranked by degree and PageRank."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import networkx as nx
import pandas as pd

from aml.common.config import HubConfig
from aml.graph.network.inputs import NetworkInputs, fmt_ts, rule_version
from aml.monitoring.recording import AlertRecord

RULE_ID = "NET_HUB"
HUB_FEATURES = [
    "account_id",
    "in_degree",
    "out_degree",
    "in_vnd",
    "out_vnd",
    "pagerank",
    "pagerank_ratio",
]


@dataclass(frozen=True)
class HubResult:
    alerts: tuple[AlertRecord, ...]
    features: pd.DataFrame  # HUB_FEATURES, one row per account, sorted by account_id
    active_accounts: int  # accounts with at least one edge in the lookback graph


def _graph(window: pd.DataFrame) -> nx.DiGraph:
    """Unweighted directed graph; nodes and edges are added in sorted order."""
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_nodes_from(sorted(set(window["src"]) | set(window["dst"])))
    graph.add_edges_from(sorted(set(zip(window["src"], window["dst"], strict=True))))
    return graph


def _features(
    accounts: pd.Series, window: pd.DataFrame, graph: nx.DiGraph, alpha: float
) -> pd.DataFrame:
    active = len(graph)
    rank = nx.pagerank(graph, alpha=alpha, weight=None, tol=1e-10, max_iter=200) if active else {}
    inflow = window.groupby("dst")["amt"].sum().to_dict()
    outflow = window.groupby("src")["amt"].sum().to_dict()
    ids = list(accounts)
    return pd.DataFrame(
        {
            "account_id": ids,
            "in_degree": [graph.in_degree(a) if a in graph else 0 for a in ids],
            "out_degree": [graph.out_degree(a) if a in graph else 0 for a in ids],
            "in_vnd": [int(inflow.get(a, 0)) for a in ids],
            "out_vnd": [int(outflow.get(a, 0)) for a in ids],
            "pagerank": [round(rank.get(a, 0.0), 8) for a in ids],
            "pagerank_ratio": [round(rank.get(a, 0.0) * active, 4) for a in ids],
        },
        columns=HUB_FEATURES,
    )


def _alert(row: Any, window: pd.DataFrame, active: int) -> AlertRecord:
    account = str(row.account_id)
    in_vnd, ratio = int(row.in_vnd), float(row.pagerank_ratio)
    in_degree = int(row.in_degree)
    ev = window[window["dst"] == account]
    start, end = ev["txn_ts"].min().to_pydatetime(), ev["txn_ts"].max().to_pydatetime()
    reason = (
        f"received {in_vnd:,} VND from {in_degree} accounts of other customers in {len(ev)} "
        f"transfers between {fmt_ts(start)} and {fmt_ts(end)}; PageRank {ratio:.2f}x the "
        f"average of {active} active accounts"
    )
    details: dict[str, object] = {
        "in_degree": in_degree,
        "out_degree": int(row.out_degree),
        "in_vnd": in_vnd,
        "out_vnd": int(row.out_vnd),
        "pagerank_ratio": ratio,
        "active_accounts": active,
        "transfers": len(ev),
    }
    return AlertRecord(
        RULE_ID,
        rule_version(RULE_ID),
        "ACCOUNT",
        account,
        ((account, "SUBJECT"),),
        start,
        end,
        tuple(sorted(ev["txn_id"])),
        in_vnd,
        reason,
        details,
        f"{RULE_ID}|{account}",
    )


def detect_hubs(inputs: NetworkInputs, cfg: HubConfig) -> HubResult:
    since = pd.Timestamp(inputs.cutoff) - pd.Timedelta(days=cfg.lookback_days)
    t = inputs.transfers
    window = t[(t["txn_ts"] >= since).to_numpy()].reset_index(drop=True)
    graph = _graph(window)
    features = _features(inputs.accounts["account_id"], window, graph, cfg.pagerank_alpha)
    is_hub = (
        (features["in_degree"] >= cfg.min_in_degree)
        & (features["pagerank_ratio"] >= cfg.min_pagerank_ratio)
        & (features["in_vnd"] >= cfg.min_inflow_vnd)
    )
    alerts = tuple(
        _alert(row, window, len(graph)) for row in features[is_hub].itertuples(index=False)
    )
    return HubResult(alerts, features, len(graph))
