"""Oracle / DuckDB -> Neo4j projection sync: incremental by `txn_ts`, customer side swept by run.

Oracle stays the system of record; this only reads the source and writes the Neo4j projection
(plus one `graph_sync_runs` row and one audit row). Steps are numbered as in specs/neo4j-sync.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import neo4j
import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.neo4j import client, sync_record
from aml.graph.neo4j.extract import (
    NODE_LABELS,
    REL_TYPES,
    Projection,
    SyncError,
    build_projection,
    open_source,
    to_rows,
)

PROBE_SINCE = datetime(2999, 1, 1)  # reads the customer side, finds no transfers: a cheap check
BOTH_SIDES = "FROM transactions WHERE from_account_id IS NOT NULL AND to_account_id IS NOT NULL"
ATTRIBUTE_MERGES = ("merge_devices", "merge_phones", "merge_addresses")  # node + relationship


@dataclass(frozen=True)
class SyncRun:
    run_id: int
    mode: str  # "FULL" | "INCREMENTAL"
    source_backend: str
    source_user: str | None  # None on DuckDB
    since: datetime | None  # where transfers were read from; None = everything
    watermark_from: datetime | None
    watermark_to: datetime | None
    er_run_id: int
    sent: dict[str, int]  # 11 keys: rows sent to MERGE in this run
    graph: dict[str, int]  # 11 keys: nodes / relationships in Neo4j after the run
    source: dict[str, int]  # {"TRANSFERRED_TO": .., "SENT_TO": ..} counted at the source
    pruned: int  # relationships older than the oldest transaction still at the source
    swept: int  # customer-side nodes + relationships no longer at the source
    lag_before_seconds: int | None
    lag_after_seconds: int
    seconds: float
    in_sync: bool


@dataclass(frozen=True)
class SourceStats:
    transfers: int  # two-sided transactions
    daily_edges: int  # acct_edge_daily rows
    first_ts: datetime | None
    last_ts: datetime | None


@dataclass(frozen=True)
class Plan:
    run_id: int
    mode: str
    since: datetime | None
    watermark_from: datetime | None
    latest_before: datetime | None  # newest two-sided txn_ts at the source when the run began


def plan_since(watermark: datetime | None, overlap_minutes: int, *, full: bool) -> datetime | None:
    """Where to start reading transfers: nothing for FULL / first run, else watermark - overlap."""
    if full or watermark is None:
        return None
    return watermark - timedelta(minutes=overlap_minutes)


# ---------------------------------------------------------------- measurements
def _ts(value: Any) -> datetime | None:
    return None if value is None or bool(pd.isna(value)) else pd.Timestamp(value).to_pydatetime()


def source_stats(source: Database) -> SourceStats:
    t = source.query_df(f"SELECT COUNT(*) AS n, MIN(txn_ts) AS lo, MAX(txn_ts) AS hi {BOTH_SIDES}")
    e = source.query_df("SELECT COUNT(*) AS n FROM acct_edge_daily")
    return SourceStats(
        int(t["n"].iloc[0]), int(e["n"].iloc[0]), _ts(t["lo"].iloc[0]), _ts(t["hi"].iloc[0])
    )


def _lag(latest: datetime | None, watermark: datetime | None) -> int | None:
    if latest is None or watermark is None:
        return None
    return max(0, int((latest - watermark).total_seconds()))


def graph_counts(driver: neo4j.Driver, settings: Settings) -> dict[str, int]:
    frame = client.run_read_file(driver, settings, "read/counts.cypher")
    by_name = dict(zip(frame["name"], frame["n"], strict=True))
    return {k: int(by_name[k]) for k in (*NODE_LABELS, *REL_TYPES)}


def read_state(driver: neo4j.Driver, settings: Settings) -> tuple[datetime | None, str] | None:
    """(watermark, source backend) of the last sync, or None when the graph was never synced."""
    frame = client.run_read_file(driver, settings, "read/sync_state.cypher")
    if frame.empty:
        return None
    row = frame.iloc[0]
    return _ts(row["txn_watermark"]), str(row["source_backend"])


# ---------------------------------------------------------------- the writes (steps 5-7)
def _load(
    driver: neo4j.Driver, settings: Settings, name: str, rows: list[dict[str, Any]], **params: Any
) -> None:
    client.run_write_file(driver, settings, f"sync/{name}.cypher", params, rows=rows)


def _write_customer_side(
    driver: neo4j.Driver, settings: Settings, proj: Projection, run_id: int
) -> int:
    """Step 5: customers, their accounts and attributes, then sweep what is gone. Returns swept."""
    f = proj.frames
    accounts = f["Account"]
    _load(driver, settings, "merge_customers", to_rows(f["Customer"]), run_id=run_id)
    _load(driver, settings, "merge_accounts", to_rows(accounts[~accounts["is_external"]]))
    _load(driver, settings, "merge_owns", to_rows(f["OWNS"]), run_id=run_id)
    for name, rel in zip(ATTRIBUTE_MERGES, ("USES_DEVICE", "HAS_PHONE", "LIVES_AT"), strict=True):
        _load(driver, settings, name, to_rows(f[rel]), run_id=run_id)
    done = client.run_write_file(driver, settings, "sync/sweep.cypher", {"run_id": run_id})
    return done["nodes_deleted"] + done["relationships_deleted"]


def _write_account_side(driver: neo4j.Driver, settings: Settings, proj: Projection) -> None:
    """Step 6: external accounts, then transfers and daily edges between accounts."""
    f = proj.frames
    accounts = f["Account"]
    external = to_rows(accounts.loc[accounts["is_external"], ["account_id"]])
    _load(driver, settings, "merge_external_accounts", external)
    _load(driver, settings, "merge_transfers", to_rows(f["TRANSFERRED_TO"]))
    _load(driver, settings, "merge_daily_edges", to_rows(f["SENT_TO"]))


def _prune(driver: neo4j.Driver, settings: Settings, first_ts: datetime | None) -> int:
    """Step 7: drop relationships older than the oldest two-sided transaction at the source."""
    if first_ts is None:
        return 0
    params: dict[str, Any] = {"min_ts": first_ts, "min_day": first_ts.date()}
    done = client.run_write_file(driver, settings, "sync/prune.cypher", params)
    return done["relationships_deleted"]


# ---------------------------------------------------------------- run_sync
def run_sync(
    db: Database, settings: Settings, *, full: bool = False, actor: str | None = None
) -> SyncRun:
    """Sync the projection. Preconditions fail without writing anything; a failure after the first
    write is audited as SYNC_FAILED and raised as SyncError (state and run log stay as they were).
    """
    started = time.perf_counter()
    source = open_source(db, settings)
    try:
        return _sync(db, source, settings, full, actor, started)
    finally:
        if source is not db:
            source.close()


def _sync(
    db: Database,
    source: Database,
    settings: Settings,
    full: bool,
    actor: str | None,
    started: float,
) -> SyncRun:
    # 1. Check the source before Neo4j is opened; nothing is written yet.
    read_since = None if full else PROBE_SINCE
    projection = build_projection(source, since=read_since)
    driver = client.open_driver(settings)
    try:
        state = read_state(driver, settings)
        # 2. A graph built from another backend is replaced only on request.
        if state is not None and state[1] != db.backend and not full:
            raise SyncError(
                f"graph was synced from {state[1]} but the source is {db.backend}: run with --full"
            )
        # 3-4. Mode, read window, run id.
        mode = "FULL" if full or state is None else "INCREMENTAL"
        watermark_from = state[0] if state is not None and mode == "INCREMENTAL" else None
        since = plan_since(watermark_from, settings.graph_sync.overlap_minutes, full=full)
        if since != read_since:
            projection = build_projection(source, since=since)
        plan = Plan(
            sync_record.next_run_id(db), mode, since, watermark_from, source_stats(source).last_ts
        )
        try:
            return _write(db, source, driver, settings, projection, plan, actor, started)
        except Exception as exc:
            try:
                sync_record.audit_failed(db, plan.run_id, mode, exc, actor)
            except Exception as audit_exc:  # keep the original failure visible
                exc.add_note(f"SYNC_FAILED audit row was not written: {audit_exc}")
            raise SyncError(f"{mode} sync failed: {exc}") from exc
    finally:
        driver.close()


def _write(
    db: Database,
    source: Database,
    driver: neo4j.Driver,
    settings: Settings,
    proj: Projection,
    plan: Plan,
    actor: str | None,
    started: float,
) -> SyncRun:
    # 3. FULL wipes first; the schema is always (re)applied.
    if plan.mode == "FULL":
        client.run_write_file(driver, settings, "sync/wipe.cypher")
    client.run_write_file(driver, settings, "schema.cypher")
    swept = _write_customer_side(driver, settings, proj, plan.run_id)  # 5
    _write_account_side(driver, settings, proj)  # 6
    after = source_stats(source)
    pruned = _prune(driver, settings, after.first_ts)  # 7
    # 8. Compare the graph with the source.
    graph = graph_counts(driver, settings)
    counted = {"TRANSFERRED_TO": after.transfers, "SENT_TO": after.daily_edges}
    in_sync = all(graph[k] == counted[k] for k in counted)
    # 9. Watermark, state node, run log, audit.
    known = [t for t in (plan.watermark_from, proj.max_ts) if t is not None]
    watermark_to = max(known, default=None)
    client.run_write_file(
        driver,
        settings,
        "sync/save_state.cypher",
        {
            "watermark": watermark_to,
            "source_backend": db.backend,
            "er_run_id": proj.er_run_id,
            "run_id": plan.run_id,
        },
    )
    lag_after = _lag(after.last_ts, watermark_to)
    run = SyncRun(
        run_id=plan.run_id,
        mode=plan.mode,
        source_backend=db.backend,
        source_user=settings.graph_sync.oracle_user if source is not db else None,
        since=plan.since,
        watermark_from=plan.watermark_from,
        watermark_to=watermark_to,
        er_run_id=proj.er_run_id,
        sent={k: len(proj.frames[k]) for k in (*NODE_LABELS, *REL_TYPES)},
        graph=graph,
        source=counted,
        pruned=pruned,
        swept=swept,
        lag_before_seconds=None
        if plan.mode == "FULL"
        else _lag(plan.latest_before, plan.watermark_from),
        lag_after_seconds=0 if lag_after is None else lag_after,
        seconds=round(time.perf_counter() - started, 2),
        in_sync=in_sync,
    )
    sync_record.record_run(db, run)
    sync_record.audit_synced(db, run, actor)
    return run
