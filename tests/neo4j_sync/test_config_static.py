"""AC1 for specs/neo4j-sync.md: config, compose, DDL 140, grants, Cypher files, docs."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from aml.common.config import PROJECT_ROOT, load_settings
from aml.common.db import DuckDb

from .helpers import CONSTRAINTS, GRAPH_SYNC_GRANTS, INDEXES, READ_PROCEDURES, mod

CYPHER_DIR = PROJECT_ROOT / "src" / "aml" / "graph" / "neo4j" / "cypher"


def test_ac1_config_defaults() -> None:
    settings = load_settings(environ={})
    assert settings.neo4j.database == "neo4j"
    assert settings.neo4j.read_procedures == READ_PROCEDURES
    assert settings.graph_sync.oracle_user == "aml_graph_sync_usr"
    assert settings.graph_sync.batch_size == 5000
    assert settings.graph_sync.overlap_minutes == 60


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"AML__GRAPH_SYNC__BATCH_SIZE": "0"}, "batch_size must be between 1 and 50000"),
        ({"AML__GRAPH_SYNC__BATCH_SIZE": "50001"}, "batch_size must be between 1 and 50000"),
        ({"AML__GRAPH_SYNC__OVERLAP_MINUTES": "-1"}, "overlap_minutes must be >= 0"),
        ({"AML__GRAPH_SYNC__ORACLE_USER": "bad name"}, "oracle_user must be a plain identifier"),
    ],
)
def test_ac1_config_validation_errors(env: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        load_settings(environ=env)


def test_ac1_batch_size_bounds_are_inclusive() -> None:
    low = load_settings(environ={"AML__GRAPH_SYNC__BATCH_SIZE": "1"})
    high = load_settings(environ={"AML__GRAPH_SYNC__BATCH_SIZE": "50000"})
    assert (low.graph_sync.batch_size, high.graph_sync.batch_size) == (1, 50000)


def test_ac1_docker_compose_disables_usage_report_and_pins_image() -> None:
    compose = yaml.safe_load((PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    neo4j = compose["services"]["neo4j"]
    assert neo4j["environment"]["NEO4J_dbms_usage__report_enabled"] == "false"
    assert neo4j["image"] == "neo4j:5.26.31-community"


def test_ac1_schema_scripts_order() -> None:
    scripts = mod("aml.dba.schema").SCHEMA_SCRIPTS
    last = {"duckdb": "ddl/050_customers_masked.sql", "oracle": "ddl/050_security_objects.sql"}
    for backend, security in last.items():
        order = list(scripts[backend])
        assert "ddl/140_graph_sync.sql" in order, backend
        assert order.index("ddl/130_network.sql") < order.index("ddl/140_graph_sync.sql"), backend
        assert order.index("ddl/140_graph_sync.sql") < order.index(security), backend


def test_ac1_apply_schema_twice_creates_table_and_view(duck: DuckDb) -> None:
    schema = mod("aml.dba.schema")
    schema.apply_schema(duck)
    schema.apply_schema(duck)
    assert int(duck.query_df("SELECT COUNT(*) FROM graph_sync_runs").iloc[0, 0]) == 0
    view = duck.query_df("SELECT * FROM graph_customer_attrs")
    assert set(view.columns) == {
        "cif",
        "phone",
        "device_id",
        "street",
        "ward",
        "district",
        "province",
    }
    assert len(view.columns) == 7


def test_ac1_role_grants_and_grants_script() -> None:
    grants = mod("aml.dba.security").ROLE_GRANTS["aml_graph_sync"]
    assert {(p.upper(), o.upper()) for p, o in grants} == GRAPH_SYNC_GRANTS
    assert len(grants) == 7
    text = (PROJECT_ROOT / "sql" / "oracle" / "security" / "020_grants.sql").read_text(
        encoding="utf-8"
    )
    for table in ("graph_customer_attrs", "customer_golden", "admin_unit_mapping"):
        assert f"GRANT SELECT ON {table} TO aml_graph_sync" in text, table


def test_ac1_schema_cypher_statements() -> None:
    statements = mod("aml.graph.neo4j.client").load_statements("schema.cypher")
    assert len(statements) == 9
    assert sum("CREATE CONSTRAINT" in s for s in statements) == 7
    assert sum("CREATE INDEX" in s for s in statements) == 2
    assert all("IF NOT EXISTS" in s for s in statements)
    joined = "\n".join(statements)
    for name in sorted(CONSTRAINTS | INDEXES):
        assert name in joined, name


def test_ac1_merge_files_are_single_unwind_merge_statements() -> None:
    client = mod("aml.graph.neo4j.client")
    files = sorted((CYPHER_DIR / "sync").glob("merge_*.cypher"))
    assert len(files) == 9, [f.name for f in files]
    for path in files:
        statements = client.load_statements(f"sync/{path.name}")
        assert len(statements) == 1, path.name
        assert "UNWIND $rows AS row" in statements[0], path.name
        assert "MERGE" in statements[0], path.name
    transfers = client.load_statements("sync/merge_transfers.cypher")[0]
    assert "TRANSFERRED_TO" in transfers
    assert "txn_id" in transfers


def test_ac1_wipe_deletes_relationships_first_in_batches() -> None:
    statements = mod("aml.graph.neo4j.client").load_statements("sync/wipe.cypher")
    assert len(statements) == 13
    for statement in statements[:7]:
        assert "DELETE r" in statement
        assert "DETACH" not in statement
    assert all("IN TRANSACTIONS" in s for s in statements)


def test_ac1_read_files_are_single_read_only_statements() -> None:
    client = mod("aml.graph.neo4j.client")
    guard = mod("aml.graph.neo4j.guard")
    files = sorted((CYPHER_DIR / "read").glob("*.cypher"))
    assert {f.name for f in files} >= {"sync_state.cypher", "counts.cypher"}
    for path in files:
        statements = client.load_statements(f"read/{path.name}")
        assert len(statements) == 1, path.name
        guard.assert_read_only(statements[0])


def test_ac1_no_cypher_file_uses_apoc_or_unscoped_call() -> None:
    files = list(CYPHER_DIR.rglob("*.cypher"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "apoc." not in text.lower(), path.name
        assert "CALL {" not in text, path.name


def test_ac1_cypher_file_and_split_statements() -> None:
    client = mod("aml.graph.neo4j.client")
    with pytest.raises(FileNotFoundError):
        client.cypher_file("nope.cypher")
    assert client.cypher_file("schema.cypher").is_file()
    parts = client.split_statements("MATCH (n) RETURN n;\n// note\nMATCH (m)\nRETURN m;\n")
    assert len(parts) == 2
    assert all(";" not in p for p in parts)
    with pytest.raises(ValueError):
        client.split_statements("MATCH (n) RETURN n")


def test_ac1_docs_exist_with_required_phrases() -> None:
    path = PROJECT_ROOT / "docs" / "neo4j-sync.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    for phrase in ("Sync lag", "Consistency", "--full", "not anonymisation"):
        assert phrase in text, phrase
