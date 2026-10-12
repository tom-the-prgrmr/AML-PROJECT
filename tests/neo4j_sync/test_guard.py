"""AC2 for specs/neo4j-sync.md: the pure-Python read-only guard `assert_read_only`."""

from __future__ import annotations

import pytest

from .helpers import mod

PREFIX = "write clause {} is not allowed in a read-only query"

ALLOWED = [
    ("MATCH (a:Account {account_id: $id})-[r:TRANSFERRED_TO]->(b) RETURN b.account_id, r.amount "
     "ORDER BY r.ts LIMIT 10", ()),
    ("MATCH (n) WHERE n.note CONTAINS 'please DELETE and CREATE' RETURN count(n)", ()),
    ("// SET x\nMATCH (n) RETURN n.created_at, n.offset LIMIT 1", ()),
    ("MATCH (n:`CREATE`) RETURN count(n)", ()),
    ("MATCH (a:Account) CALL { WITH a MATCH (a)<-[:OWNS]-(c) RETURN count(c) AS n } "
     "RETURN a.account_id, n", ()),
    ("MATCH (a:Account) CALL (a) { MATCH (a)<-[:OWNS]-(c) RETURN count(c) AS n } "
     "RETURN a.account_id, n", ()),
    ("EXPLAIN MATCH (n) RETURN n LIMIT 1", ()),
    ("MATCH (n) RETURN count(n);", ()),
    ("SHOW CONSTRAINTS YIELD name RETURN name", ()),
    ("CALL db.labels() YIELD label RETURN label", ("db.labels",)),
    ("CALL gds.pageRank.stream('g') YIELD nodeId RETURN nodeId", ("gds.*.stream",)),
]  # fmt: skip

BLOCKED = [
    ("CREATE (n:X)", (), PREFIX.format("CREATE")),
    ("match (n) set n.x = 1", (), "SET"),
    ("MERGE (n:X {id: 1})", (), "MERGE"),
    ("MATCH (n) DETACH DELETE n", (), "DETACH"),
    ("MATCH (n) DELETE n", (), "DELETE"),
    ("MATCH (n) REMOVE n.x", (), "REMOVE"),
    ("DROP CONSTRAINT account_id_unique", (), "DROP"),
    ("MATCH (n) FOREACH (x IN [1] | SET n.x = x)", (), "FOREACH"),
    ("LOAD CSV FROM 'file:///x.csv' AS row RETURN row", (), "LOAD"),
    ("MATCH (n) WHERE n.url = 'http://x' SET n.y = 1", (), "SET"),
    ("MATCH (n)\nSET\tn.x = 1", (), "SET"),
    ("MATCH (n) RETURN n.set", (), "SET"),
    ("CALL apoc.create.node(['X'], {})", (),
     "procedure apoc.create.node is not allowed in a read-only query"),
    ("CALL gds.pageRank.write('g', {writeProperty: 'pr'})", ("gds.*.stream",),
     "gds.pageRank.write"),
    ("CALL db.labels()", (), "db.labels"),
    ("MATCH (n) RETURN n; MATCH (m) RETURN m", (), "multiple statements are not allowed"),
    ("", (), "empty query"),
    ("   ", (), "empty query"),
    ("// only a comment", (), "empty query"),
]  # fmt: skip


@pytest.mark.parametrize(("cypher", "procedures"), ALLOWED)
def test_ac2_read_queries_pass(cypher: str, procedures: tuple[str, ...]) -> None:
    mod("aml.graph.neo4j.guard").assert_read_only(cypher, allowed_procedures=procedures)


@pytest.mark.parametrize(("cypher", "procedures", "message"), BLOCKED)
def test_ac2_write_and_unsafe_queries_are_blocked(
    cypher: str, procedures: tuple[str, ...], message: str
) -> None:
    guard = mod("aml.graph.neo4j.guard")
    if message.isupper():  # a bare keyword stands for the full "write clause <KW> ..." message
        message = PREFIX.format(message)
    with pytest.raises(guard.WriteBlockedError) as exc:
        guard.assert_read_only(cypher, allowed_procedures=procedures)
    assert message in str(exc.value)


def test_ac2_error_hierarchy_and_keyword_list() -> None:
    guard = mod("aml.graph.neo4j.guard")
    assert issubclass(guard.WriteBlockedError, guard.GraphError)
    assert issubclass(guard.GraphError, RuntimeError)
    assert "CALL" not in guard.WRITE_KEYWORDS
    assert {
        "CREATE",
        "MERGE",
        "SET",
        "DELETE",
        "DETACH",
        "REMOVE",
        "DROP",
        "FOREACH",
        "LOAD",
    } <= set(guard.WRITE_KEYWORDS)
    assert {"ALTER", "RENAME", "GRANT", "DENY", "REVOKE", "TERMINATE"} <= set(guard.WRITE_KEYWORDS)


def test_ac2_earliest_keyword_is_reported() -> None:
    guard = mod("aml.graph.neo4j.guard")
    with pytest.raises(guard.WriteBlockedError) as exc:
        guard.assert_read_only("MATCH (n) SET n.x = 1 DELETE n")
    assert PREFIX.format("SET") in str(exc.value)
