"""AC8 for specs/neo4j-sync.md: the read path (guard + READ session) against a real Neo4j."""

from __future__ import annotations

from datetime import date
from typing import Any

import neo4j
import pytest
from neo4j.exceptions import ClientError

from aml.common.db import DuckDb, ServiceUnavailableError

from .conftest import Neo
from .helpers import client, graph_audit, mod, neo_settings, one, run_sync

ACCESS_MODE = "Neo.ClientError.Statement.AccessMode"
BLOCKED_QUERY = "MATCH (a:Account) SET a.flag = 1"


@pytest.fixture
def synced(mini: DuckDb, neo: Neo) -> Neo:
    run_sync(mini, neo.settings, full=True)
    return neo


def _n(neo: Neo, cypher: str) -> int:
    return int(one(neo.driver, neo.settings, cypher))


@pytest.mark.neo4j
def test_ac8_run_read_returns_dataframes_with_python_types(synced: Neo) -> None:
    c, d, s = client(), synced.driver, synced.settings
    frame = c.run_read(d, s, "MATCH (a:Account) RETURN count(a) AS n")
    assert list(frame.columns) == ["n"]
    assert len(frame) == 1
    assert int(frame.iloc[0, 0]) == 24

    opened = c.run_read(
        d, s, "MATCH (a:Account {account_id: $id}) RETURN a.open_date AS d", {"id": "A01"}
    ).iloc[0, 0]
    assert type(opened) is date
    assert opened == date(2025, 1, 1)

    counts = c.run_read_file(d, s, "read/counts.cypher")
    assert len(counts) > 0

    labels = c.run_read(d, s, "CALL db.labels() YIELD label RETURN label")
    assert sorted(labels["label"]) == [
        "Account",
        "Address",
        "Customer",
        "Device",
        "Phone",
        "SyncState",
    ]


@pytest.mark.neo4j
def test_ac8_guard_blocks_writes_and_audits_only_when_asked(synced: Neo, mini: DuckDb) -> None:
    c, d, s = client(), synced.driver, synced.settings
    guard = mod("aml.graph.neo4j.guard")
    before = len(graph_audit(mini))

    with pytest.raises(guard.WriteBlockedError, match="SET"):
        c.run_read(d, s, BLOCKED_QUERY, audit_db=mini, actor="analyst01")
    rows = graph_audit(mini, "decision = 'QUERY_BLOCKED'")
    assert len(graph_audit(mini)) == before + 1
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["entity_type"] == "cypher"
    assert row["actor"] == "analyst01"
    assert row["version"] == "guard/v2"
    assert row["details"]["query"] == BLOCKED_QUERY

    with pytest.raises(guard.WriteBlockedError):
        c.run_read(d, s, BLOCKED_QUERY)
    assert len(graph_audit(mini)) == before + 1

    with pytest.raises(guard.WriteBlockedError):
        c.run_read(d, s, "CALL apoc.create.node(['X'], {})")


@pytest.mark.neo4j
def test_ac8_server_rejects_writes_in_a_read_session_even_without_the_guard(synced: Neo) -> None:
    d, s = synced.driver, synced.settings

    def attempt(cypher: str, how: str) -> None:
        with d.session(database=s.neo4j.database, default_access_mode=neo4j.READ_ACCESS) as session:
            with pytest.raises(ClientError) as exc:
                if how == "execute_read":
                    session.execute_read(lambda tx: tx.run(cypher).consume())
                else:
                    session.run(cypher).consume()
            assert exc.value.code == ACCESS_MODE
            assert "Writing in read access mode not allowed" in str(exc.value)

    attempt("CREATE (:Intruder)", "execute_read")
    attempt("MERGE (:Intruder {a: 1})", "execute_read")
    attempt(BLOCKED_QUERY, "execute_read")
    attempt("CREATE (:Intruder)", "run")


@pytest.mark.neo4j
def test_ac8_run_write_file_refuses_read_files_and_graph_is_untouched(synced: Neo) -> None:
    c = client()
    with pytest.raises(mod("aml.graph.neo4j.guard").GraphError, match="not a write file"):
        c.run_write_file(synced.driver, synced.settings, "read/counts.cypher")
    assert _n(synced, "MATCH (n:Intruder) RETURN count(n) AS n") == 0
    assert _n(synced, "MATCH (a:Account) WHERE a.flag IS NOT NULL RETURN count(a) AS n") == 0
    assert _n(synced, "MATCH (a:Account) RETURN count(a) AS n") == 24


def test_ac8_open_driver_without_neo4j_raises_service_unavailable() -> None:
    settings = neo_settings(AML__NEO4J__URI="bolt://127.0.0.1:1")
    with pytest.raises(ServiceUnavailableError):
        client().open_driver(settings)


def test_ac8_write_prefixes() -> None:
    prefixes: Any = client().WRITE_PREFIXES
    assert tuple(prefixes) == ("schema.cypher", "sync/")
