"""Network side of the case enrichment: choose the graph feature source, roll accounts up.

Only tables already written back to the system of record are read; Neo4j is never contacted.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from aml.cases.values import iso_date, lower_columns, plain, whole
from aml.common.db import Database

NETWORKX, GDS, NONE = "networkx", "gds", "none"
_VIEW = {NETWORKX: "nx_account_features_current", GDS: "gds_account_features_current"}
_COLUMNS = {
    NETWORKX: ("in_degree", "out_degree", "in_vnd", "out_vnd", "pagerank_ratio",
               "shared_cluster_id", "shared_cluster_size", "cycle_alerts", "is_hub"),
    GDS: ("in_degree", "out_degree", "in_vnd", "out_vnd", "pagerank_ratio",
          "shared_cluster_id", "shared_cluster_size", "wcc_size", "louvain_size"),
}  # fmt: skip
FEATURE_KEYS = (
    "in_degree", "out_degree", "in_vnd", "out_vnd", "pagerank_ratio", "shared_cluster_id",
    "shared_cluster_size", "cycle_alerts", "is_hub", "wcc_size", "louvain_size",
)  # fmt: skip
_MAX = (
    "in_degree", "out_degree", "pagerank_ratio", "shared_cluster_size", "is_hub", "wcc_size",
    "louvain_size",
)  # fmt: skip
_SUM = ("in_vnd", "out_vnd", "cycle_alerts")


def _count(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def _gds_is_current(db: Database, as_of: date) -> bool:
    """GDS rows exist and the latest GDS run was made for the same as_of as this case run."""
    if _count(db, f"SELECT COUNT(*) FROM {_VIEW[GDS]}") == 0:
        return False
    latest = db.query_df(
        "SELECT as_of FROM gds_runs WHERE run_id = (SELECT MAX(run_id) FROM gds_runs)"
    )
    return not latest.empty and iso_date(latest.iloc[0, 0]) == as_of.isoformat()


def choose_source(db: Database, mode: str, as_of: date) -> str:
    """``networkx`` | ``gds`` | ``none`` (the chosen table has no rows)."""
    if mode == "auto":
        mode = GDS if _gds_is_current(db, as_of) else NETWORKX
    return mode if _count(db, f"SELECT COUNT(*) FROM {_VIEW[mode]}") else NONE


def load_features(db: Database, source: str) -> pd.DataFrame:
    """Account features of the source, indexed by ``account_id`` (empty for ``none``)."""
    if source == NONE:
        return pd.DataFrame(index=pd.Index([], name="account_id"))
    columns = ", ".join(_COLUMNS[source])
    df = lower_columns(db.query_df(f"SELECT account_id, {columns} FROM {_VIEW[source]}"))
    return df.set_index("account_id")


def golden_features(features: pd.DataFrame, account_ids: list[str]) -> dict[str, Any]:
    """MAX / SUM of the account rows of one golden customer; a key the source lacks is None."""
    out: dict[str, Any] = dict.fromkeys(FEATURE_KEYS)
    rows = features.loc[features.index.intersection(account_ids)]
    if rows.empty:
        return out
    for key in _MAX + _SUM:
        if key in rows:
            value = rows[key].max() if key in _MAX else rows[key].sum()
            out[key] = plain(value) if key == "pagerank_ratio" else whole(value)
    clusters = rows["shared_cluster_id"].dropna()
    out["shared_cluster_id"] = str(clusters.min()) if len(clusters) else None
    return out


def network_block(
    source: str, features: dict[str, Any], counterparties: list[dict[str, Any]], shared: list[str]
) -> dict[str, Any]:
    return {
        "source": source,
        "features": features,
        "counterparties": counterparties,
        "shared_alert_cases": shared,
    }
