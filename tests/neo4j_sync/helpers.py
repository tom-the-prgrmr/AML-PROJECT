"""Helpers for the Phase 6a tests (specs/neo4j-sync.md): MINI-G, LATE, S11, Neo4j access."""

from __future__ import annotations

import importlib
import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import pandas as pd

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import Database
from aml.dba.edges import refresh_acct_edge_daily
from tests.network.helpers import M, add_txns, load_shr

NODE_ORDER = ("Customer", "Account", "Device", "Phone", "Address")
REL_ORDER = ("OWNS", "USES_DEVICE", "HAS_PHONE", "LIVES_AT", "TRANSFERRED_TO", "SENT_TO")
KEYS_11 = NODE_ORDER + REL_ORDER

READ_PROCEDURES = [
    "db.labels",
    "db.relationshipTypes",
    "db.propertyKeys",
    "db.schema.visualization",
    "db.schema.nodeTypeProperties",
    "db.schema.relTypeProperties",
    "dbms.components",
]
CONSTRAINTS = {
    "customer_id_unique",
    "account_id_unique",
    "device_key_unique",
    "phone_key_unique",
    "address_key_unique",
    "sync_state_name_unique",
    "transfer_txn_unique",
}
INDEXES = {"transfer_ts_idx", "sent_day_idx"}
GRAPH_SYNC_GRANTS = {
    ("SELECT", t.upper())
    for t in (
        "customers_masked",
        "accounts",
        "transactions",
        "acct_edge_daily",
        "graph_customer_attrs",
        "customer_golden",
        "admin_unit_mapping",
    )
}
OFFLINE_URI = "bolt://127.0.0.1:1"
MINI_S11 = (20, 24, 14, 10, 14, 23, 17, 17, 17, 8, 7)
TINY_S11 = (273, 1314, 264, 267, 265, 532, 279, 273, 273, 3651, 3575)


def mod(name: str) -> Any:
    return importlib.import_module(name)


def duck_settings(**env: str) -> Settings:
    """Settings of the spec: ``load_settings(environ={"DB_BACKEND": "duckdb"})`` (+ overrides)."""
    return load_settings(environ={"DB_BACKEND": "duckdb", **env})


def neo_settings(**env: str) -> Settings:
    """Same, plus ``.env`` so that NEO4J_PASSWORD reaches the settings (needed for a real Neo4j)."""
    return load_settings(environ={**read_environ(), "DB_BACKEND": "duckdb", **env})


def s11(*values: int) -> dict[str, int]:
    assert len(values) == 11
    return dict(zip(KEYS_11, values, strict=True))


def ts(text: str) -> datetime:
    return datetime.fromisoformat(text)


def day(value: Any) -> date:
    return pd.Timestamp(value).date()


def scalar(db: Database, sql: str) -> Any:
    return db.query_df(sql).iloc[0, 0]


def count(db: Database, table: str, where: str = "") -> int:
    return int(scalar(db, f"SELECT COUNT(*) FROM {table} {where}"))


def cells(frame: pd.DataFrame) -> list[Any]:
    """Every cell of ``frame`` as a Python object (lists stay lists)."""
    return [v for row in frame.itertuples(index=False) for v in row]


def as_list(value: Any) -> list[Any]:
    return list(value)


def col(frame: pd.DataFrame, name: str) -> list[Any]:
    return list(frame[name])


def none_if_nan(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return value
    return None if value is None or bool(pd.isna(value)) else value


# ---------------------------------------------------------------- MINI-G and LATE
def load_mini_g(db: Database) -> None:
    """MINI-G of the spec: MINI-SHR plus T08, T09, then `refresh_acct_edge_daily`."""
    load_shr(db)
    add_txns(
        db,
        [
            ("T08", "2026-03-06 09:00:00", "A02", None, 9 * M),
            ("T09", "2026-03-01 15:00:00", "A02", "A01", 4 * M),
        ],
    )
    db.execute("UPDATE transactions SET channel = 'CASH' WHERE txn_id = 'T08'")
    refresh_acct_edge_daily(db)


def add_late(db: Database) -> None:
    """LATE of the spec: T10, T11, T12, then `refresh_acct_edge_daily`."""
    add_txns(
        db,
        [
            ("T10", "2026-07-01 09:30:00", "A03", "A02", 2 * M),
            ("T11", "2026-07-01 08:00:00", "A03", "A02", 1 * M),
            ("T12", "2026-07-02 10:00:00", "A05", "EXT-02", 3 * M),
        ],
    )
    refresh_acct_edge_daily(db)


# ---------------------------------------------------------------- audit rows
def graph_audit(db: Database, where: str = "") -> pd.DataFrame:
    """audit_log rows of module 'graph' with ``details`` parsed."""
    expr = "JSON_SERIALIZE(details)" if db.backend == "oracle" else "details"
    extra = f"AND {where}" if where else ""
    df = db.query_df(
        "SELECT entity_type, entity_id, decision, reason, actor, version, "
        f"{expr} AS details FROM audit_log WHERE module = 'graph' {extra} ORDER BY audit_id"
    )
    df.columns = [c.lower() for c in df.columns]
    parsed: list[Any] = [json.loads(d) if isinstance(d, str) else d for d in df["details"]]
    df["details"] = parsed
    return df


# ---------------------------------------------------------------- Neo4j access (spec interface)
def client() -> Any:
    return mod("aml.graph.neo4j.client")


def sync_mod() -> Any:
    return mod("aml.graph.neo4j.sync")


def read(driver: Any, settings: Settings, cypher: str, params: Any = None) -> pd.DataFrame:
    return client().run_read(driver, settings, cypher, params)


def one(driver: Any, settings: Settings, cypher: str, params: Any = None) -> Any:
    return read(driver, settings, cypher, params).iloc[0, 0]


def rows_of(
    driver: Any, settings: Settings, cypher: str, params: Any = None
) -> list[tuple[Any, ...]]:
    df = read(driver, settings, cypher, params)
    return [tuple(none_if_nan(v) for v in r) for r in df.itertuples(index=False)]


def total_nodes(driver: Any, settings: Settings) -> int:
    return int(one(driver, settings, "MATCH (n) RETURN count(n) AS n"))


def total_rels(driver: Any, settings: Settings) -> int:
    return int(one(driver, settings, "MATCH ()-[r]->() RETURN count(r) AS n"))


def state_row(driver: Any, settings: Settings) -> tuple[Any, ...]:
    rows = rows_of(
        driver,
        settings,
        "MATCH (s:SyncState {name: 'projection'}) RETURN s.last_run_id AS run, "
        "toString(s.txn_watermark) AS wm, s.source_backend AS src, s.er_run_id AS er",
    )
    assert len(rows) == 1
    return rows[0]


def run_sync(db: Database, settings: Settings, **kw: Any) -> Any:
    return sync_mod().run_sync(db, settings, **kw)


def keys_of(names: Sequence[str]) -> set[str]:
    return set(names)


def graph_snapshot(driver: Any, settings: Settings) -> dict[str, list[tuple[Any, ...]]]:
    """The five comparable sets of AC10 (sorted lists of tuples)."""
    queries = {
        "customers": "MATCH (c:Customer) RETURN c.golden_customer_id AS g, c.cifs AS cifs",
        "accounts": (
            "MATCH (a:Account) RETURN a.account_id AS id, a.cif AS cif, a.account_type AS t, "
            "a.is_external AS ext, toString(a.open_date) AS od"
        ),
        "customer_rels": (
            "MATCH (c:Customer)-[r:OWNS|USES_DEVICE|HAS_PHONE|LIVES_AT]->(x) "
            "RETURN c.golden_customer_id AS g, type(r) AS t, coalesce(x.key, x.account_id) AS k"
        ),
        "transfers": (
            "MATCH (a:Account)-[r:TRANSFERRED_TO]->(b:Account) RETURN r.txn_id AS id, "
            "a.account_id AS s, b.account_id AS d, r.amount AS amt, toString(r.ts) AS ts, "
            "r.channel AS ch"
        ),
        "daily": (
            "MATCH (a:Account)-[r:SENT_TO]->(b:Account) RETURN a.account_id AS s, "
            "b.account_id AS d, toString(r.day) AS day, r.count AS n, r.total AS total"
        ),
    }
    out: dict[str, list[tuple[Any, ...]]] = {}
    for name, cypher in queries.items():
        rows = []
        for row in rows_of(driver, settings, cypher):
            rows.append(tuple(tuple(v) if isinstance(v, list) else v for v in row))
        out[name] = sorted(rows, key=repr)
    return out
