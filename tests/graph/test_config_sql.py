"""AC1 for specs/fund-flow-trace.md: config, SCHEMA_SCRIPTS, METHODS and the trace SQL files."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from aml.common.config import load_settings
from aml.common.db import SQL_ROOT, split_oracle_script, sql_file
from aml.dba.schema import SCHEMA_SCRIPTS

from .helpers import PATH_COLUMNS, mod

DDL = "ddl/120_property_graph.sql"


def test_ac1_default_trace_config() -> None:
    t = load_settings(environ={}).trace
    assert t.default_hops == 3
    assert t.default_hours == 72
    assert t.max_hops == 6
    assert t.max_hours == 720
    assert t.max_paths == 100_000
    assert t.edge_min_amount_vnd == 10_000_000
    assert t.edge_top_k == 5


def test_ac1_max_hops_above_six_is_rejected() -> None:
    with pytest.raises(ValidationError):
        load_settings(environ={"AML__TRACE__MAX_HOPS": "7"})


def test_ac1_ddl_120_is_registered_for_oracle_only() -> None:
    oracle = SCHEMA_SCRIPTS["oracle"]
    assert DDL in oracle
    assert oracle.index(DDL) < oracle.index("ddl/050_security_objects.sql")
    assert oracle.index(DDL) > oracle.index("ddl/100_entity_resolution.sql")
    assert oracle.index(DDL) > oracle.index("ddl/110_monitoring.sql")
    assert DDL not in SCHEMA_SCRIPTS["duckdb"]
    assert not (SQL_ROOT / "duckdb" / DDL).exists()


def test_ac1_ddl_120_content() -> None:
    text = sql_file(DDL, "oracle").read_text(encoding="utf-8")
    assert "PROPERTY GRAPH" in text.upper()
    assert "aml_fund_flow" in text.lower()
    assert "acct_node" in text.lower()
    assert split_oracle_script(text)  # every statement is '/'-terminated


def test_ac1_methods_registry() -> None:
    trace = mod("aml.graph.trace")
    methods = trace.METHODS
    # Phase 6b-i (specs/neo4j-queries.md AC1) registers `neo4j` as the fourth method.
    assert list(methods) == ["cte_raw", "cte_edge", "pgq", "neo4j"]
    assert [methods[n].name for n in methods] == ["cte_raw", "cte_edge", "pgq", "neo4j"]
    assert methods["cte_raw"].backends == frozenset({"oracle", "duckdb"})
    assert methods["cte_edge"].backends == frozenset({"oracle", "duckdb"})
    assert methods["pgq"].backends == frozenset({"oracle"})
    assert methods["neo4j"].backends == frozenset({"oracle", "duckdb"})
    assert [methods[n].exact for n in methods] == [True, False, True, True]
    assert trace.PATH_COLUMNS == PATH_COLUMNS
    assert trace.PATH_SEPARATOR == ">"


@pytest.mark.parametrize("name", ["cte_raw", "cte_edge"])
def test_ac1_cte_sql_files_per_backend(name: str) -> None:
    ora = sql_file(f"trace/{name}.sql", "oracle")
    duck = sql_file(f"trace/{name}.sql", "duckdb")
    assert ora == SQL_ROOT / "oracle" / "trace" / f"{name}.sql"
    assert duck == SQL_ROOT / "duckdb" / "trace" / f"{name}.sql"
    ora_text = ora.read_text(encoding="utf-8")
    assert "CYCLE" in ora_text
    assert re.search(r"SET\s+is_cycle", ora_text, re.IGNORECASE)
    assert not re.search(r"\bCYCLE\b", duck.read_text(encoding="utf-8"), re.IGNORECASE)


def test_ac1_pgq_sql_is_oracle_only_with_six_blocks() -> None:
    assert (SQL_ROOT / "oracle" / "trace" / "pgq.sql").exists()
    assert not (SQL_ROOT / "duckdb" / "trace" / "pgq.sql").exists()
    assert not (SQL_ROOT / "common" / "trace" / "pgq.sql").exists()
    statements = split_oracle_script(sql_file("trace/pgq.sql", "oracle").read_text("utf-8"))
    assert len(statements) == 1
    assert statements[0].count("GRAPH_TABLE") == 6


def test_ac1_pgq_query_text_keeps_first_n_blocks() -> None:
    trace = mod("aml.graph.trace")
    text = trace.METHODS["pgq"].query_text
    assert text("oracle", trace.TraceRequest("A", 2, 24)).count("GRAPH_TABLE") == 2
    assert text("oracle", trace.TraceRequest("A", 6, 24)).count("GRAPH_TABLE") == 6


def test_ac1_query_text_never_inlines_the_account() -> None:
    trace = mod("aml.graph.trace")
    request = trace.TraceRequest("A9999999999", 3, 72)
    for name, backend in (("cte_raw", "duckdb"), ("cte_edge", "duckdb"), ("cte_raw", "oracle")):
        assert "A9999999999" not in trace.METHODS[name].query_text(backend, request)


def test_ac1_no_curly_braces_in_trace_sql() -> None:
    files = list(SQL_ROOT.glob("*/trace/*.sql"))
    assert len(files) >= 5
    for path in files:
        assert "{" not in path.read_text(encoding="utf-8"), path
