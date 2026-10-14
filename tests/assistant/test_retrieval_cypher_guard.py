"""AC4 and AC5 for specs/assistant-retrievers.md: `validate_cypher`, fully offline."""

from __future__ import annotations

import pytest

from aml.graph.neo4j.guard import GraphError, assert_read_only

from .rt_helpers import CQ, V, guard_mod

TWO_PARAMS = ("case_id", "golden_customer_id")
A = "MATCH (a:Account)"


# ---------------------------------------------------------------- AC4: allowed subset
def test_ac4_limit_is_appended() -> None:
    r = V(CQ)
    assert r.text == CQ + " LIMIT 20"
    assert r.limit == 20
    assert r.original_limit is None


def test_ac4_small_limit_is_kept() -> None:
    r = V(CQ + " LIMIT 5")
    assert r.text == CQ + " LIMIT 5"
    assert r.limit == 5
    assert r.original_limit == 5


def test_ac4_big_limit_is_replaced() -> None:
    r = V(CQ + " LIMIT 500")
    assert r.text.endswith("DESC LIMIT 20")
    assert r.limit == 20
    assert r.original_limit == 500


def test_ac4_lower_case_limit_and_trailing_semicolon() -> None:
    assert V(f"{A} RETURN a.account_id limit 7;").text == f"{A} RETURN a.account_id limit 7"


def test_ac4_a_limit_in_the_middle_does_not_count() -> None:
    q = (
        f"{A} WITH a LIMIT 3 MATCH (a)-[r:TRANSFERRED_TO]->(b:Account) "
        "RETURN a.account_id, r.txn_id"
    )
    assert V(q).text.endswith("r.txn_id LIMIT 20")


def test_ac4_keywords_semicolons_and_slashes_inside_a_string_are_ignored() -> None:
    V(f"{A} WHERE a.account_id = 'DELETE; DROP // x' RETURN a.account_id")


def test_ac4_aggregation_with_localdatetime_is_unchanged() -> None:
    q = (
        "MATCH (a:Account)<-[r:TRANSFERRED_TO]-(:Account) "
        "WHERE r.ts >= localdatetime('2026-04-01T00:00:00') AND r.amount >= 100000000 "
        "RETURN a.account_id, count(r) AS transfers, sum(r.amount) AS total "
        "ORDER BY total DESC LIMIT 10"
    )
    assert V(q).text == q


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (a:Account)-[:TRANSFERRED_TO*1..3]->(b:Account) WHERE a.account_id = 'A01' "
        "RETURN DISTINCT b.account_id",
        "MATCH (c:Customer)-[:USES_DEVICE|HAS_PHONE]->(v)<-[:USES_DEVICE|HAS_PHONE]-(o:Customer) "
        "RETURN c.golden_customer_id, o.golden_customer_id",
        "MATCH (a:Account)-[r:SENT_TO]->(b:Account) WHERE r.day >= date('2026-06-01') "
        "RETURN a.account_id, sum(r.total) AS total",
    ],
)
def test_ac4_other_allowed_shapes(query: str) -> None:
    V(query)


def test_ac4_case_parameters_are_allowed_when_declared() -> None:
    q = (
        "MATCH (c:Case {case_id: $case_id})-[m:MATCHES_TYPOLOGY]->(t:Typology) "
        "RETURN t.typology_id, t.name, m.evidence_ids"
    )
    V(q, TWO_PARAMS)


def test_ac4_results_pass_the_6a_guard_and_are_deterministic() -> None:
    for query in (CQ, CQ + " LIMIT 500", f"{A} RETURN a.account_id limit 7;"):
        first = V(query)
        assert_read_only(first.text, allowed_procedures=())
        assert V(query) == first


# ---------------------------------------------------------------- AC5: forbidden queries
BIG_IN = (
    "MATCH (a:Account) WHERE a.account_id IN ["
    + ", ".join(["'A01'"] * 500)
    + "] RETURN a.account_id"
)

FORBIDDEN: list[tuple[str, str, str | None]] = [
    ("", "empty", None),
    ("  ;", "empty", None),
    (BIG_IN, "too_long", None),
    ("MATCH (a:`Account`) RETURN a.account_id", "backtick", None),
    (f"{A} RETURN a.account_id // LIMIT 1", "comment", None),
    (f"{A} /* x */ RETURN a.account_id", "comment", None),
    (f"{A} SET a.flag = 1 RETURN a.account_id", "guard", "write clause SET"),
    ("MATCH (n) DETACH DELETE n", "guard", "DETACH"),
    ("CREATE (:Account {account_id: 'X'})", "guard", "CREATE"),
    (f"{A} MERGE (a)-[:OWNS]->(a) RETURN a.account_id", "guard", "MERGE"),
    ("LOAD CSV FROM 'file:///x' AS row RETURN row", "guard", "LOAD"),
    (f"{A} RETURN a.account_id; MATCH (n) DETACH DELETE n", "guard", "multiple statements"),
    ("CALL db.labels()", "guard", "procedure db.labels"),
    ("CALL apoc.cypher.run('MATCH (n) DETACH DELETE n', {})", "guard", "procedure apoc.cypher.run"),
    (
        "CALL db.index.vector.queryNodes('i', 5, [0.1]) YIELD node RETURN node",
        "guard",
        "procedure db.index.vector.queryNodes",
    ),
    (
        "MATCH (s:Account) MATCH (t:Account) RETURN gds.graph.project('g', s, t)",
        "guard",
        "procedure gds.graph.project",
    ),
    (
        f"{A} CALL {{ WITH a MATCH (a)-[r:TRANSFERRED_TO]->() RETURN count(r) AS n }} "
        "RETURN a.account_id, n",
        "clause",
        "CALL",
    ),
    (
        f"{A} RETURN a.account_id UNION MATCH (c:Customer) "
        "RETURN c.golden_customer_id AS account_id",
        "clause",
        "UNION",
    ),
    ("UNWIND range(1, 1000000000) AS x RETURN count(x)", "clause", "UNWIND"),
    ("SHOW PROCEDURES YIELD name RETURN name", "clause", "SHOW"),
    (f"EXPLAIN {A} RETURN a.account_id", "clause", "EXPLAIN"),
    (f"PROFILE {A} RETURN a.account_id", "clause", "PROFILE"),
    ("RETURN 1", "clause", "must start with MATCH"),
    (A, "clause", "RETURN"),
    (f"{A} RETURN a.account_id LIMIT $n", "parameter", "$n"),
    ("MATCH (c:Case {case_id: $case_id}) RETURN c.case_id", "parameter", "$case_id"),
    ("MATCH (s:SyncState) RETURN s.txn_watermark", "label", "SyncState"),
    ("MATCH (c:Chunk) RETURN c.chunk_id", "label", "Chunk"),
    ("MATCH (a:Account)-[:PAID]->(b:Account) RETURN b.account_id", "label", "PAID"),
    ("MATCH (n) WHERE n IS SyncState RETURN n.name", "label", None),
    (f"{A} RETURN a.password", "property", "password"),
    ("MATCH (t:Typology) RETURN t.embedding", "property", "embedding"),
    ("MATCH (a:Account {secret: 1}) RETURN a.account_id", "property", "secret"),
    (f"{A} RETURN apoc.text.join(['a'], ',') AS x", "function", "apoc.text.join"),
    (
        "MATCH p = shortestPath((a:Account)-[:TRANSFERRED_TO*..3]->(b:Account)) RETURN length(p)",
        "function",
        "shortestPath",
    ),
    ("MATCH (a:Account)-[:TRANSFERRED_TO*]->(b:Account) RETURN b.account_id", "path", "unbounded"),
    (
        "MATCH (a:Account)-[:TRANSFERRED_TO*1..6]->(b:Account) RETURN b.account_id",
        "path",
        "longer than 3",
    ),
    (
        "MATCH ((x:Account)-[:TRANSFERRED_TO]->(y:Account)){1,5} RETURN y.account_id",
        "path",
        "quantified",
    ),
]


@pytest.mark.parametrize(
    ("query", "rule", "fragment"),
    FORBIDDEN,
    ids=[f"{i:02d}-{rule}" for i, (_, rule, _) in enumerate(FORBIDDEN)],
)
def test_ac5_forbidden_queries(query: str, rule: str, fragment: str | None) -> None:
    error = guard_mod().CypherRejectedError
    with pytest.raises(error) as caught:
        V(query)
    assert caught.value.rule == rule
    if fragment is not None:
        assert fragment in str(caught.value)


# Not in the spec's list: holes of the allow-lists that the same rules close (fail-closed).
EXTRA_FORBIDDEN: list[tuple[str, str]] = [
    ("MATCH (n) RETURN n['text']", "property"),
    # review 8b: a subscript after a map projection, and the .* projection itself
    ("MATCH (n) RETURN n {.*}['text'] AS t", "property"),
    ('MATCH (n) RETURN n{.*}["embedding"]', "property"),
    ("MATCH (n) WHERE n {.*}['text'] CONTAINS 'x' RETURN n.case_id", "property"),
    ("MATCH (n) RETURN n {.*} AS m", "property"),
    ("MATCH (n) RETURN n {.case_id}['text'] AS t", "property"),
    ("MATCH (n) RETURN [n.case_id][0]['text'] AS t", "property"),
    ("MATCH (n) RETURN (n)['text'] AS t", "property"),
    # review 8b: quantified path patterns in every spelling (rule 9 rejects them all)
    (
        "MATCH (a:Account) ((x)-[:TRANSFERRED_TO]->(y) WHERE true)* (b:Account) "
        "RETURN b.account_id",
        "path",
    ),
    (
        "MATCH (a:Account) ((x)-[:TRANSFERRED_TO]->(y) WHERE true)+ (b:Account) "
        "RETURN b.account_id",
        "path",
    ),
    ("MATCH (a:Account) ((x)-[:TRANSFERRED_TO]->(y)){,} (b:Account) RETURN b.account_id", "path"),
    ("MATCH (a:Account) ((x)-[:TRANSFERRED_TO]->(y)){,9} (b:Account) RETURN b.account_id", "path"),
    ("MATCH (a:Account) ((x)-[:TRANSFERRED_TO]->(y)){2} (b:Account) RETURN b.account_id", "path"),
    ("MATCH (a:Account) ( -[:TRANSFERRED_TO]-> ) + (b:Account) RETURN b.account_id", "path"),
    ("MATCH (a:Account) ( (x)-->(y) ) { 1 , 2 } (b:Account) RETURN b.account_id", "path"),
    ("MATCH (a:Account)-[:TRANSFERRED_TO]->{1,3}(b:Account) RETURN b.account_id", "path"),
    ("MATCH (a:Account)-[:TRANSFERRED_TO]-*(b:Account) RETURN b.account_id", "path"),
    ("MATCH (a:Account)-->+(b:Account) RETURN b.account_id", "path"),
    ('MATCH (n) RETURN n["embedding"]', "property"),
    (f"{A} WITH 'text' AS k MATCH (n) RETURN n[k]", "property"),
    ("MATCH (n:$('Chunk')) RETURN n.name", "parameter"),
    ("MATCH (n:!Account) RETURN n.key", "label"),
    ("MATCH (n:Account|Chunk) RETURN n.account_id", "label"),
    (f"{A} WHERE a:SyncState RETURN a.account_id", "label"),
    (f"{A} RETURN a {{.embedding}}", "property"),
    ("MATCH (a:Account)-[:TRANSFERRED_TO*2..]->(b:Account) RETURN b.account_id", "path"),
    ("MATCH (a:Account)-[:TRANSFERRED_TO*5]->(b:Account) RETURN b.account_id", "path"),
    ("MATCH (a:Account)-[:TRANSFERRED_TO]->+(b:Account) RETURN b.account_id", "path"),
    (f"{A} RETURN keys(a)", "function"),
    (f"{A} RETURN properties(a)", "function"),
    ("OPTIONAL MATCH (a:Account) DELETE a", "guard"),
]


@pytest.mark.parametrize(("query", "rule"), EXTRA_FORBIDDEN)
def test_ac5_related_holes_are_closed(query: str, rule: str) -> None:
    with pytest.raises(guard_mod().CypherRejectedError) as caught:
        V(query)
    assert caught.value.rule == rule


@pytest.mark.parametrize(
    "query",
    [
        f"{A} WHERE a.account_id IN ['A01', 'A02'] RETURN a.account_id",
        "MATCH (t:Typology) RETURN t.typology_id, t.rule_ids[0], labels(t)[0]",
        "MATCH (c:Case)-[m:MATCHES_TYPOLOGY]->(:Typology) RETURN c.case_id, m.evidence_ids[0..3]",
        "OPTIONAL MATCH (a:Account {account_id: 'A01', is_external: false}) RETURN a.account_id",
        "MATCH p = (a:Account)-[:TRANSFERRED_TO*3]->(b:Account) RETURN length(p), b.account_id",
        "MATCH (a:Account)-[r:TRANSFERRED_TO]->(b:Account) "
        "WHERE r.ts >= localdatetime('2026-04-01T00:00:00') - duration({days: 7}) "
        "RETURN a.account_id, avg(r.amount) AS mean, toString(max(r.ts)) AS latest",
        # review 8b: arithmetic after a nested call is not a quantified path
        "MATCH (a:Account)-[r:TRANSFERRED_TO]->(:Account) RETURN toFloat(count(r)) * 100 AS m",
        "MATCH (a:Account)-[r:TRANSFERRED_TO]->(:Account) RETURN round(avg(r.amount)) + 1 AS m",
        "MATCH (a:Account)-[r:TRANSFERRED_TO]->(:Account) RETURN size(collect(r)) * 2 AS m",
        "MATCH (a:Account)-[r:TRANSFERRED_TO]->(:Account) RETURN sum(abs(r.amount)) * 2 AS m",
        "MATCH (a:Account) RETURN ((1+2)) * 2 AS m, (a.account_id) + 'x' AS s",
        "MATCH (a:Account) RETURN [1, 2, 3][0] AS x, [a.account_id] AS ids",
        "MATCH (t:Typology) WITH t, [x IN t.rule_ids | x] AS ids RETURN ids[0..2]",
        "MATCH (a:Account) RETURN a.account_id, a {.account_id, .cif} AS m",
    ],
)
def test_ac4_related_shapes_stay_allowed(query: str) -> None:
    assert_read_only(V(query).text, allowed_procedures=())


def test_ac5_rejection_is_a_graph_error() -> None:
    assert issubclass(guard_mod().CypherRejectedError, GraphError)


def test_ac5_every_rule_is_exercised() -> None:
    assert set(guard_mod().RULES) == {rule for _, rule, _ in FORBIDDEN}
