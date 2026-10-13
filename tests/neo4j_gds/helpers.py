"""Helpers for the Phase 6b-ii tests (specs/neo4j-gds.md)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database
from tests.neo4j_queries.helpers import (
    OFFLINE_URI,
    Synced,
    cli,
    graph_audit,
    mod,
    neo_settings,
    set_env,
    synced_db,
)
from tests.neo4j_sync.helpers import (
    MINI_S11,
    TINY_S11,
    client,
    load_mini_g,
    none_if_nan,
    rows_of,
    run_sync,
    s11,
    scalar,
    total_nodes,
    total_rels,
)

__all__ = [
    "FEATURE_COLUMNS",
    "MINI_S11",
    "OFFLINE_URI",
    "TINY_S11",
    "VALUE_COLUMNS",
    "NeoState",
    "Synced",
    "cli",
    "feature_frame",
    "feature_tuple",
    "gds",
    "gds_graph_count",
    "graph_audit",
    "load_mini_g",
    "mod",
    "neo_settings",
    "neo_state",
    "none_if_nan",
    "parse_json",
    "run_gds",
    "run_sync",
    "s11",
    "scalar",
    "set_env",
    "synced_db",
]

FEATURE_COLUMNS = [
    "account_id",
    "in_degree",
    "out_degree",
    "in_vnd",
    "out_vnd",
    "pagerank",
    "pagerank_ratio",
    "wcc_id",
    "wcc_size",
    "louvain_id",
    "louvain_size",
    "shared_cluster_id",
    "shared_cluster_size",
]
VALUE_COLUMNS = FEATURE_COLUMNS[1:]
# (in_degree, out_degree, in_vnd, out_vnd, pagerank_ratio, wcc_id, wcc_size, louvain_id,
#  louvain_size, shared_cluster_id, shared_cluster_size) as written in the spec
TUPLE_COLUMNS = [c for c in VALUE_COLUMNS if c != "pagerank"]


def gds() -> Any:
    return mod("aml.graph.neo4j.gds")


def run_gds(db: Database, settings: Settings, **kw: Any) -> Any:
    return gds().run_gds(db, settings, **kw)


def parse_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def feature_frame(
    db: Database, run_id: int | None = None, table: str = "gds_account_features"
) -> pd.DataFrame:
    """Rows of a feature table (lower-case columns, sorted by account_id)."""
    where = f"WHERE run_id = {run_id}" if run_id is not None else ""
    frame = db.query_df(f"SELECT * FROM {table} {where} ORDER BY account_id")
    frame.columns = [c.lower() for c in frame.columns]
    return frame.reset_index(drop=True)


def feature_tuple(frame: pd.DataFrame, account: str) -> tuple[Any, ...]:
    """The spec's 11-tuple of an account (pagerank itself is left out, see `pagerank_of`)."""
    row = frame[frame["account_id"] == account]
    assert len(row) == 1, account
    values = row.iloc[0]
    return tuple(_plain(values[c]) for c in TUPLE_COLUMNS)


def _plain(value: Any) -> Any:
    value = none_if_nan(value)
    if hasattr(value, "item") and not isinstance(value, str):
        value = value.item()
    return value


@dataclass(frozen=True)
class NeoState:
    """What a `run_gds` must leave unchanged in Neo4j (spec AC3)."""

    graphs: int
    nodes: int
    rels: int
    node_keys: frozenset[str]
    rel_keys: frozenset[str]


def gds_graph_count(synced: Synced) -> int:
    frame = client().run_read(
        synced.driver,
        synced.settings,
        "CALL gds.graph.list() YIELD graphName RETURN count(*) AS n",
        procedures=("gds.graph.list",),
    )
    return int(frame.iloc[0, 0])


def neo_state(synced: Synced) -> NeoState:
    d, s = synced.driver, synced.settings
    node_keys = rows_of(d, s, "MATCH (n) UNWIND keys(n) AS k RETURN DISTINCT k")
    rel_keys = rows_of(d, s, "MATCH ()-[r]->() UNWIND keys(r) AS k RETURN DISTINCT k")
    return NeoState(
        gds_graph_count(synced),
        total_nodes(d, s),
        total_rels(d, s),
        frozenset(r[0] for r in node_keys),
        frozenset(r[0] for r in rel_keys),
    )
