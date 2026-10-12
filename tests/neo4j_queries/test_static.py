"""AC1 for specs/neo4j-queries.md: config, Cypher files, registry, query_params, docs."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from aml.common.config import PROJECT_ROOT, load_settings
from aml.graph.model import TraceRequest
from tests.neo4j_sync.helpers import READ_PROCEDURES

from .helpers import mod

QUERIES_DIR = PROJECT_ROOT / "src" / "aml" / "graph" / "neo4j" / "cypher" / "queries"
FILES = {
    "trace.cypher",
    "cycles.cypher",
    "shared_attributes.cypher",
    "shared_cluster.cypher",
    "fan_in.cypher",
    "fan_out.cypher",
}
NAMES = ("cycles", "shared_attributes", "shared_cluster", "fan_in", "fan_out")


def _statement(name: str) -> str:
    statements = mod("aml.graph.neo4j.client").load_statements(f"queries/{name}")
    assert len(statements) == 1, name
    return statements[0]


def test_ac1_config_defaults_and_validation() -> None:
    settings = load_settings(environ={})
    assert settings.neo4j.read_timeout_seconds == 60
    assert settings.graph_queries.max_rows == 10_000
    assert settings.neo4j.read_procedures == READ_PROCEDURES
    with pytest.raises(ValidationError, match="read_timeout_seconds must be > 0"):
        load_settings(environ={"AML__NEO4J__READ_TIMEOUT_SECONDS": "0"})
    with pytest.raises(ValidationError, match="max_rows must be >= 1"):
        load_settings(environ={"AML__GRAPH_QUERIES__MAX_ROWS": "0"})


def test_ac1_query_directory_has_exactly_six_files() -> None:
    assert {p.name for p in QUERIES_DIR.glob("*.cypher")} == FILES


@pytest.mark.parametrize("name", sorted(FILES))
def test_ac1_each_file_is_one_read_only_statement(name: str) -> None:
    settings = load_settings(environ={})
    statement = _statement(name)
    assert "$row_limit" in statement
    assert "apoc." not in statement
    assert "CALL {" not in statement
    mod("aml.graph.neo4j.guard").assert_read_only(
        statement, allowed_procedures=settings.neo4j.read_procedures
    )


def test_ac1_trace_and_cycles_statement_shape() -> None:
    trace = _statement("trace.cypher")
    for parameter in ("$account", "$hops", "$hours", "$since"):
        assert parameter in trace
    assert trace.count("CALL (") == 5
    assert "){" not in trace
    assert "{2,5}" in _statement("cycles.cypher")


def test_ac1_methods_registry_has_neo4j_fourth() -> None:
    methods = mod("aml.graph.trace").METHODS
    assert list(methods) == ["cte_raw", "cte_edge", "pgq", "neo4j"]
    neo = methods["neo4j"]
    assert neo.backends == frozenset({"oracle", "duckdb"})
    assert neo.exact is True
    assert neo.uses_filters is False
    assert neo.prepare is not None
    assert all(methods[n].prepare is None for n in ("cte_raw", "cte_edge", "pgq"))


def test_ac1_neo4j_query_text_is_the_file_statement_for_any_request() -> None:
    text = mod("aml.graph.trace").METHODS["neo4j"].query_text
    short = text("duckdb", TraceRequest("A", 2, 24))
    long = text("oracle", TraceRequest("A9999999999", 6, 720))
    assert short == long == _statement("trace.cypher")
    assert "A9999999999" not in long


def test_ac1_trace_unavailable_is_a_trace_error() -> None:
    model = mod("aml.graph.model")
    assert issubclass(model.TraceUnavailableError, model.TraceError)


def test_ac1_query_names_and_columns() -> None:
    queries = mod("aml.graph.neo4j.queries")
    assert queries.QUERY_NAMES == NAMES
    assert queries.QUERY_COLUMNS["cycles"] == [
        "length",
        "path",
        "step_path",
        "first_ts",
        "last_ts",
        "first_vnd",
        "last_vnd",
    ]
    assert queries.QUERY_COLUMNS["shared_attributes"] == [
        "kind",
        "key",
        "customers",
        "customer_ids",
    ]
    assert queries.QUERY_COLUMNS["shared_cluster"] == ["customer", "distance", "via", "accounts"]
    fan = ["account_id", "window_start", "window_end", "counterparties", "transfers", "total_vnd"]
    assert queries.QUERY_COLUMNS["fan_in"] == fan
    assert queries.QUERY_COLUMNS["fan_out"] == fan


def test_ac1_query_params_from_config() -> None:
    params = mod("aml.graph.neo4j.queries").query_params
    settings = load_settings(environ={})
    assert params("cycles", settings) == {
        "min_length": 3,
        "max_length": 5,
        "window_hours": 168,
        "min_amount": 50_000_000,
        "min_amount_ratio": 0.7,
        "cutoff": datetime(2026, 7, 1, 0, 0, 0),
        "account": None,
        "row_limit": 10_001,
    }
    assert params("fan_in", settings, account="A1", as_of=date(2026, 3, 3)) == {
        "window_days": 7,
        "min_counterparties": 8,
        "min_total_vnd": 100_000_000,
        "cutoff": datetime(2026, 3, 4, 0, 0, 0),
        "account": "A1",
        "row_limit": 10_001,
    }
    assert params("shared_cluster", settings, customer="G-C01") == {
        "max_customers_per_value": 50,
        "customer": "G-C01",
        "row_limit": 10_001,
    }


def test_ac1_query_params_errors() -> None:
    queries = mod("aml.graph.neo4j.queries")
    settings = load_settings(environ={})
    with pytest.raises(
        queries.QueryError, match="cycles, shared_attributes, shared_cluster, fan_in, fan_out"
    ):
        queries.query_params("nope", settings)
    with pytest.raises(queries.QueryError, match="customer"):
        queries.query_params("shared_cluster", settings)
    with pytest.raises(queries.QueryError, match="does not take"):
        queries.query_params("shared_attributes", settings, account="A1")
    with pytest.raises(queries.QueryError, match="does not take"):
        queries.query_params("cycles", settings, customer="G-C01")


def test_ac1_docs_exist_with_required_terms() -> None:
    text = (PROJECT_ROOT / "docs" / "neo4j-queries.md").read_text(encoding="utf-8")
    for term in ("quantified path pattern", "read_timeout_seconds", "out of sync"):
        assert term in text, term
