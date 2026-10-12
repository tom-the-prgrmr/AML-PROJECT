"""AC6 and AC7 for specs/neo4j-sync.md: `run_sync` against a real Neo4j on MINI-G."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from aml.common.db import DuckDb

from .conftest import Neo
from .helpers import (
    CONSTRAINTS,
    INDEXES,
    MINI_S11,
    add_late,
    client,
    count,
    graph_audit,
    mod,
    one,
    rows_of,
    run_sync,
    s11,
    state_row,
    sync_mod,
    total_nodes,
    total_rels,
)

pytestmark = pytest.mark.neo4j

NODE_PROPS = {
    "account_id", "account_type", "branch_id", "cif", "cif_count", "cifs", "currency",
    "er_run_id", "golden_customer_id", "is_external", "key", "last_run_id", "name",
    "open_date", "source_backend", "synced_run", "txn_watermark", "updated_at",
}  # fmt: skip
REL_PROPS = {"amount", "channel", "cif", "count", "day", "synced_run", "total", "ts", "txn_id"}
FULL_REASON = (
    "FULL sync from duckdb: sent 82 nodes and 89 relationships, pruned 0, swept 0; "
    "graph has 8 of 8 transfers and 7 of 7 daily edges; watermark 2026-07-01 10:00:00"
)


@pytest.fixture
def first(mini: DuckDb, neo: Neo) -> Any:
    """MINI-G after `run_sync(full=True)` (run 1)."""
    return run_sync(mini, neo.settings, full=True)


def _source_counts(db: DuckDb) -> tuple[int, ...]:
    return tuple(count(db, t) for t in ("transactions", "accounts", "customers", "er_golden"))


def test_ac6_full_sync_result(first: Any) -> None:
    run = first
    assert run.run_id == 1
    assert run.mode == "FULL"
    assert run.source_backend == "duckdb"
    assert run.source_user is None
    assert run.since is None
    assert run.watermark_from is None
    assert run.watermark_to == datetime(2026, 7, 1, 10, 0, 0)
    assert run.er_run_id == 1
    assert run.sent == s11(*MINI_S11)
    assert run.graph == s11(*MINI_S11)
    assert run.source == {"TRANSFERRED_TO": 8, "SENT_TO": 7}
    assert (run.pruned, run.swept) == (0, 0)
    assert run.lag_before_seconds is None
    assert run.lag_after_seconds == 0
    assert run.in_sync is True


def test_ac6_full_sync_graph_content(first: Any, neo: Neo) -> None:
    d, s = neo.driver, neo.settings
    assert total_nodes(d, s) == 83  # 82 projection nodes + SyncState
    assert total_rels(d, s) == 89

    cust = rows_of(
        d,
        s,
        "MATCH (c:Customer {golden_customer_id: 'G-C06'}) RETURN c.cifs AS cifs, c.cif_count AS n",
    )
    assert [(list(c), int(n)) for c, n in cust] == [(["C06", "C07", "C08"], 3)]

    t03 = rows_of(
        d,
        s,
        "MATCH (:Account {account_id: 'A01'})-[r:TRANSFERRED_TO {txn_id: 'T03'}]->(b) "
        "RETURN b.account_id AS dst, b.is_external AS ext, r.amount AS amount, "
        "toString(r.ts) AS ts, r.channel AS channel",
    )
    assert [(a, bool(b), int(c), e, f) for a, b, c, e, f in t03] == [
        ("EXT-01", True, 25_000_000, "2026-03-03T10:00:00", "INTERNAL_TRANSFER")
    ]
    daily = rows_of(
        d,
        s,
        "MATCH (:Account {account_id: 'A02'})-[r:SENT_TO]->(:Account {account_id: 'A01'}) "
        "RETURN toString(r.day) AS day, r.count AS n, r.total AS total",
    )
    assert [(a, int(b), int(c)) for a, b, c in daily] == [("2026-03-01", 2, 14_000_000)]
    shared = rows_of(
        d,
        s,
        "MATCH (:Customer {golden_customer_id: 'G-C01'})-[:HAS_PHONE]->(:Phone)"
        "<-[:HAS_PHONE]-(c:Customer) RETURN c.golden_customer_id AS id",
    )
    assert shared == [("G-C02",)]
    owner = rows_of(
        d,
        s,
        "MATCH (c:Customer)-[o:OWNS]->(:Account {account_id: 'A01S'}) "
        "RETURN c.golden_customer_id AS id, o.cif AS cif",
    )
    assert owner == [("G-C01", "C01")]
    assert (
        int(one(d, s, "MATCH (:Account {account_id: 'EXT-01'})<-[:OWNS]-(c) RETURN count(c) AS n"))
        == 0
    )


def test_ac6_property_names_constraints_and_state(first: Any, neo: Neo) -> None:
    d, s = neo.driver, neo.settings
    node_keys = {r[0] for r in rows_of(d, s, "MATCH (n) UNWIND keys(n) AS k RETURN DISTINCT k")}
    rel_keys = {
        r[0] for r in rows_of(d, s, "MATCH ()-[r]->() UNWIND keys(r) AS k RETURN DISTINCT k")
    }
    assert node_keys == NODE_PROPS
    assert rel_keys == REL_PROPS

    names = {r[0] for r in rows_of(d, s, "SHOW CONSTRAINTS YIELD name RETURN name")}
    assert names == CONSTRAINTS
    indexes = {r[0] for r in rows_of(d, s, "SHOW INDEXES YIELD name RETURN name")}
    assert indexes >= INDEXES

    states = rows_of(
        d,
        s,
        "MATCH (s:SyncState) RETURN s.name AS name, toString(s.txn_watermark) AS wm, "
        "s.source_backend AS src, s.er_run_id AS er, s.last_run_id AS last",
    )
    assert [(a, b, c, int(e), int(f)) for a, b, c, e, f in states] == [
        ("projection", "2026-07-01T10:00:00", "duckdb", 1, 1)
    ]


def test_ac6_run_record_and_audit_row(first: Any, mini: DuckDb) -> None:
    runs = mini.query_df("SELECT run_id, mode, nodes_sent, rels_sent, in_sync FROM graph_sync_runs")
    assert [tuple(r) for r in runs.itertuples(index=False)] == [(1, "FULL", 82, 89, 1)]

    audit = graph_audit(mini)
    assert len(audit) == 1
    row = audit.iloc[0]
    assert row["entity_type"] == "neo4j"
    assert row["entity_id"] == "projection"
    assert row["decision"] == "SYNCED"
    assert row["version"] == "graph_sync/v1"
    assert row["actor"] == "system"
    assert row["details"]["in_sync"] is True
    assert row["reason"] == FULL_REASON


def test_ac6_second_run_is_incremental_and_idempotent(first: Any, mini: DuckDb, neo: Neo) -> None:
    before = _source_counts(mini)
    run = run_sync(mini, neo.settings)
    assert run.run_id == 2
    assert run.mode == "INCREMENTAL"
    assert run.since == datetime(2026, 7, 1, 9, 0, 0)
    assert run.watermark_from == run.watermark_to == datetime(2026, 7, 1, 10, 0, 0)
    assert run.sent == s11(20, 23, 14, 10, 14, 23, 17, 17, 17, 1, 1)
    assert run.graph == s11(*MINI_S11)
    assert (run.pruned, run.swept) == (0, 0)
    assert run.lag_before_seconds == 0
    assert run.in_sync is True

    d, s = neo.driver, neo.settings
    assert total_nodes(d, s) == 83
    assert total_rels(d, s) == 89
    assert (
        int(one(d, s, "MATCH ()-[r:TRANSFERRED_TO {txn_id: 'T06'}]->() RETURN count(r) AS n")) == 1
    )
    assert _source_counts(mini) == before


# ------------------------------------------------------------------------------- AC7
@pytest.fixture
def after_a(first: Any, mini: DuckDb, neo: Neo) -> Any:
    add_late(mini)
    return run_sync(mini, neo.settings)


@pytest.fixture
def after_b(after_a: Any, mini: DuckDb, neo: Neo) -> Any:
    return run_sync(mini, neo.settings, full=True)


@pytest.fixture
def after_c(after_b: Any, mini: DuckDb, neo: Neo) -> Any:
    mini.execute("DELETE FROM transactions WHERE txn_ts < TIMESTAMP '2026-03-02 00:00:00'")
    mod("aml.dba.edges").refresh_acct_edge_daily(mini)
    return run_sync(mini, neo.settings)


@pytest.fixture
def after_d(after_c: Any, mini: DuckDb, neo: Neo) -> Any:
    mini.execute("UPDATE er_golden SET golden_customer_id = 'G-C01' WHERE cif = 'C02'")
    return run_sync(mini, neo.settings)


def test_ac7a_late_arrival_is_missed_and_flagged(after_a: Any, mini: DuckDb, neo: Neo) -> None:
    run = after_a
    assert run.run_id == 2
    assert run.mode == "INCREMENTAL"
    assert run.since == datetime(2026, 7, 1, 9, 0, 0)
    assert run.lag_before_seconds == 86400
    assert run.sent == s11(20, 24, 14, 10, 14, 23, 17, 17, 17, 3, 3)
    assert run.graph == s11(20, 25, 14, 10, 14, 23, 17, 17, 17, 10, 9)
    assert run.source == {"TRANSFERRED_TO": 11, "SENT_TO": 9}
    assert run.in_sync is False
    assert run.watermark_to == datetime(2026, 7, 2, 10, 0, 0)

    d, s = neo.driver, neo.settings
    assert (
        int(one(d, s, "MATCH ()-[r:TRANSFERRED_TO {txn_id: 'T11'}]->() RETURN count(r) AS n")) == 0
    )
    assert (
        bool(one(d, s, "MATCH (a:Account {account_id: 'EXT-02'}) RETURN a.is_external AS e"))
        is True
    )
    last = graph_audit(mini, "decision = 'SYNCED'").iloc[-1]
    assert last["reason"].endswith("; OUT OF SYNC: run aml graph sync --full")


def test_ac7b_full_resync_repairs(after_b: Any) -> None:
    run = after_b
    assert run.run_id == 3
    assert run.mode == "FULL"
    assert run.lag_before_seconds is None
    assert run.sent == s11(20, 25, 14, 10, 14, 23, 17, 17, 17, 11, 9)
    assert run.graph == s11(20, 25, 14, 10, 14, 23, 17, 17, 17, 11, 9)
    assert run.in_sync is True


def test_ac7c_retention_prune(after_c: Any) -> None:
    run = after_c
    assert run.run_id == 4
    assert run.since == datetime(2026, 7, 2, 9, 0, 0)
    assert run.pruned == 3  # T01, T09 and the A02 -> A01 daily edge of 2026-03-01
    assert run.swept == 0
    assert run.sent == s11(20, 24, 14, 10, 14, 23, 17, 17, 17, 1, 1)
    assert run.graph == s11(20, 25, 14, 10, 14, 23, 17, 17, 17, 9, 8)
    assert run.source == {"TRANSFERRED_TO": 9, "SENT_TO": 8}
    assert run.in_sync is True


def test_ac7d_golden_change_sweeps_customer_side(after_d: Any, neo: Neo) -> None:
    run = after_d
    assert run.run_id == 5
    assert run.swept == 5  # node G-C02 and its 4 relationships
    assert run.pruned == 0
    assert run.sent == s11(19, 24, 14, 10, 14, 23, 17, 16, 17, 1, 1)
    assert run.graph == s11(19, 25, 14, 10, 14, 23, 17, 16, 17, 9, 8)

    d, s = neo.driver, neo.settings
    cifs = rows_of(d, s, "MATCH (c:Customer {golden_customer_id: 'G-C01'}) RETURN c.cifs AS cifs")
    assert [list(c) for (c,) in cifs] == [["C01", "C02"]]
    owner = rows_of(
        d,
        s,
        "MATCH (c:Customer)-[:OWNS]->(:Account {account_id: 'A02'}) "
        "RETURN c.golden_customer_id AS g",
    )
    assert owner == [("G-C01",)]
    assert (
        int(one(d, s, "MATCH (c:Customer {golden_customer_id: 'G-C02'}) RETURN count(c) AS n")) == 0
    )


def test_ac7e_failure_keeps_state_and_rerun_recovers(
    after_d: Any, mini: DuckDb, neo: Neo, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync = sync_mod()
    original = client().run_write_file

    def failing(driver: Any, settings: Any, name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sync/merge_transfers.cypher":
            raise mod("aml.graph.neo4j.guard").GraphError("injected failure")
        return original(driver, settings, name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(client(), "run_write_file", failing)
        if hasattr(sync, "run_write_file"):
            patch.setattr(sync, "run_write_file", failing)
        with pytest.raises(mod("aml.graph.neo4j.extract").SyncError):
            run_sync(mini, neo.settings)

    assert count(mini, "graph_sync_runs") == 5
    assert state_row(neo.driver, neo.settings)[:2] == (5, "2026-07-02T10:00:00")
    failed = graph_audit(mini, "decision = 'SYNC_FAILED'")
    assert len(failed) == 1
    assert failed.iloc[0]["reason"]

    run = run_sync(mini, neo.settings)
    assert run.run_id == 6
    assert (run.swept, run.pruned) == (0, 0)
    assert run.graph == s11(19, 25, 14, 10, 14, 23, 17, 16, 17, 9, 8)
    assert run.in_sync is True
