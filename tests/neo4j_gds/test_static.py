"""AC1 for specs/neo4j-gds.md: config, compose, DDL 150, Cypher files, guard/v2, docs, offline CLI.

No test here needs Neo4j or Oracle.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from aml.common.config import PROJECT_ROOT, load_settings
from aml.common.db import DuckDb
from tests.neo4j_sync.helpers import READ_PROCEDURES

from .helpers import FEATURE_COLUMNS, OFFLINE_URI, cli, client, mod, set_env

GDS_DIR = PROJECT_ROOT / "src" / "aml" / "graph" / "neo4j" / "cypher" / "gds"
QUERIES_DIR = PROJECT_ROOT / "src" / "aml" / "graph" / "neo4j" / "cypher" / "queries"
FILES = {
    "version.cypher",
    "project_accounts.cypher",
    "project_accounts_undirected.cypher",
    "project_shared.cypher",
    "drop.cypher",
    "degree.cypher",
    "pagerank.cypher",
    "wcc_accounts.cypher",
    "louvain_accounts.cypher",
    "wcc_shared.cypher",
}
PROJECT_FILES = sorted(f for f in FILES if f.startswith("project_"))
OTHER_FILES = ["drop", "pagerank", "degree", "wcc_accounts", "louvain_accounts", "wcc_shared"]
JAR = "neo4j-graph-data-science-2.13.13.jar"
SHA256 = "17cfceb0c78e897baea3dfcdbd852dff779980bcc1eb444126338694bb053264"
DROP = "CALL gds.graph.drop('g', false) YIELD graphName RETURN graphName"
FUNCTION = "MATCH (s)-[r]->(t) RETURN gds.graph.project('g', s, t) AS g"


def _statement(name: str) -> str:
    statements = client().load_statements(f"gds/{name}")
    assert len(statements) == 1, name
    return statements[0]


def _guard() -> Any:
    return mod("aml.graph.neo4j.guard")


# ------------------------------------------------------------------------------ config
def test_ac1_config_defaults() -> None:
    settings = load_settings(environ={})
    gds = settings.gds
    assert gds.procedures == ["gds.graph.project", "gds.graph.drop", "gds.*.stream"]
    assert gds.graph_prefix == "aml_gds"
    assert gds.concurrency == 1
    assert gds.pagerank_max_iterations == 200
    assert gds.pagerank_tolerance == 1e-10
    assert gds.louvain_max_levels == 10
    assert gds.louvain_max_iterations == 10
    assert gds.louvain_tolerance == 0.0001
    assert settings.neo4j.read_procedures == READ_PROCEDURES


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"AML__GDS__CONCURRENCY": "5"}, "concurrency must be between 1 and 4"),
        ({"AML__GDS__GRAPH_PREFIX": "bad name"}, "graph_prefix must be a plain identifier"),
        ({"AML__GDS__PAGERANK_TOLERANCE": "0"}, "pagerank_tolerance must be > 0"),
    ],
)
def test_ac1_config_validation_errors(env: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        load_settings(environ=env)


# ------------------------------------------------------------------------------ compose
def test_ac1_docker_compose_pins_gds_jar_and_gitignore() -> None:
    compose = yaml.safe_load((PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["neo4j"]
    assert service["environment"]["NEO4J_PLUGINS"] == '["apoc"]'
    assert f"./docker/neo4j/plugins/{JAR}:/plugins/graph-data-science.jar" in service["volumes"]
    assert service["image"] == "neo4j:5.26.31-community"
    lines = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "docker/neo4j/plugins/*.jar" in [ln.strip() for ln in lines]


# ------------------------------------------------------------------------------ schema
def test_ac1_schema_scripts_order() -> None:
    scripts = mod("aml.dba.schema").SCHEMA_SCRIPTS
    last = {"duckdb": "ddl/050_customers_masked.sql", "oracle": "ddl/050_security_objects.sql"}
    for backend, security in last.items():
        order = list(scripts[backend])
        assert "ddl/150_gds.sql" in order, backend
        assert order.index("ddl/140_graph_sync.sql") < order.index("ddl/150_gds.sql"), backend
        assert order.index("ddl/150_gds.sql") < order.index(security), backend


def test_ac1_apply_schema_twice_creates_tables_and_view(duck: DuckDb) -> None:
    schema = mod("aml.dba.schema")
    schema.apply_schema(duck)
    schema.apply_schema(duck)
    for relation in ("gds_runs", "gds_account_features", "gds_account_features_current"):
        assert int(duck.query_df(f"SELECT COUNT(*) FROM {relation}").iloc[0, 0]) == 0, relation
    assert mod("aml.graph.neo4j.features").GDS_FEATURE_COLUMNS == FEATURE_COLUMNS
    frame = duck.query_df("SELECT * FROM gds_account_features")
    assert list(frame.columns) == ["run_id", *FEATURE_COLUMNS]


def test_ac1_role_grants_do_not_cover_gds_tables() -> None:
    grants = mod("aml.dba.security").ROLE_GRANTS
    objects = {obj.lower() for pairs in grants.values() for _, obj in pairs}
    assert not objects & {"gds_runs", "gds_account_features"}


# ------------------------------------------------------------------------------ Cypher files
def test_ac1_gds_directory_has_exactly_ten_files() -> None:
    assert {p.name for p in GDS_DIR.glob("*.cypher")} == FILES


@pytest.mark.parametrize("name", sorted(FILES))
def test_ac1_each_gds_file_is_one_read_only_statement(name: str) -> None:
    settings = load_settings(environ={})
    statement = _statement(name)
    _guard().assert_read_only(statement, allowed_procedures=settings.gds.procedures)
    lowered = statement.lower()
    for forbidden in (".write", ".mutate", "writeproperty", "mutateproperty"):
        assert forbidden not in lowered, (name, forbidden)


@pytest.mark.parametrize("stem", OTHER_FILES)
def test_ac1_gds_calls_are_blocked_with_the_ordinary_allowlist(stem: str) -> None:
    settings = load_settings(environ={})
    with pytest.raises(_guard().WriteBlockedError) as exc:
        _guard().assert_read_only(
            _statement(f"{stem}.cypher"), allowed_procedures=settings.neo4j.read_procedures
        )
    assert "procedure gds." in str(exc.value)


@pytest.mark.parametrize("name", PROJECT_FILES)
def test_ac1_projections_are_blocked_with_the_ordinary_allowlist(name: str) -> None:
    settings = load_settings(environ={})
    with pytest.raises(_guard().WriteBlockedError) as exc:
        _guard().assert_read_only(
            _statement(name), allowed_procedures=settings.neo4j.read_procedures
        )
    assert "procedure gds.graph.project is not allowed in a read-only query" in str(exc.value)


def test_ac1_write_prefixes_unchanged_and_guard_version() -> None:
    assert tuple(client().WRITE_PREFIXES) == ("schema.cypher", "sync/")
    assert _guard().GUARD_VERSION == "guard/v2"


# ------------------------------------------------------------------------------ guard/v2
def test_ac1_guard_allows_drop_procedure_only_when_allowlisted() -> None:
    guard = _guard()
    guard.assert_read_only(DROP, allowed_procedures=("gds.graph.drop",))
    with pytest.raises(guard.WriteBlockedError) as exc:
        guard.assert_read_only(DROP, allowed_procedures=())
    assert "procedure gds.graph.drop" in str(exc.value)


def test_ac1_guard_checks_gds_graph_functions_against_the_allowlist() -> None:
    guard = _guard()
    with pytest.raises(guard.WriteBlockedError) as exc:
        guard.assert_read_only(FUNCTION, allowed_procedures=("gds.*.stream",))
    assert "procedure gds.graph.project" in str(exc.value)
    guard.assert_read_only(FUNCTION, allowed_procedures=("gds.graph.project",))


def test_ac1_guard_leaves_other_gds_functions_alone() -> None:
    _guard().assert_read_only(
        "CALL gds.wcc.stream('g') YIELD nodeId RETURN gds.util.asNode(nodeId).account_id AS a",
        allowed_procedures=("gds.*.stream",),
    )


def test_ac1_guard_still_blocks_writes_after_an_allowed_call() -> None:
    guard = _guard()
    with pytest.raises(guard.WriteBlockedError) as exc:
        guard.assert_read_only(
            "CALL gds.graph.drop('g') YIELD graphName MATCH (n) DETACH DELETE n",
            allowed_procedures=("gds.graph.drop",),
        )
    assert "DETACH" in str(exc.value)


def test_ac1_guard_blocks_gds_write_procedures_even_with_the_gds_allowlist() -> None:
    guard = _guard()
    settings = load_settings(environ={})
    with pytest.raises(guard.WriteBlockedError) as exc:
        guard.assert_read_only(
            "CALL gds.pageRank.write('g', {writeProperty: 'pr'})",
            allowed_procedures=settings.gds.procedures,
        )
    assert "gds.pageRank.write" in str(exc.value)


def test_ac1_guard_keeps_its_old_keyword_behaviour() -> None:
    guard = _guard()
    with pytest.raises(guard.WriteBlockedError) as drop:
        guard.assert_read_only("DROP CONSTRAINT account_id_unique")
    assert "write clause DROP" in str(drop.value)
    with pytest.raises(guard.WriteBlockedError) as set_:
        guard.assert_read_only("MATCH (n) RETURN n.set")
    assert "SET" in str(set_.value)


@pytest.mark.parametrize(
    "name",
    [
        "trace.cypher",
        "cycles.cypher",
        "shared_attributes.cypher",
        "shared_cluster.cypher",
        "fan_in.cypher",
        "fan_out.cypher",
    ],
)
def test_ac1_6bi_queries_still_pass_the_guard(name: str) -> None:
    settings = load_settings(environ={})
    assert (QUERIES_DIR / name).is_file()
    statements = client().load_statements(f"queries/{name}")
    assert len(statements) == 1
    _guard().assert_read_only(statements[0], allowed_procedures=settings.neo4j.read_procedures)


# ------------------------------------------------------------------------------ docs
def test_ac1_docs_exist_with_required_strings() -> None:
    text = (PROJECT_ROOT / "docs" / "neo4j-gds.md").read_text(encoding="utf-8")
    for phrase in ("in-memory", "concurrency", "docker cp", SHA256):
        assert phrase in text, phrase


# ------------------------------------------------------------------------------ offline CLI
@pytest.fixture
def cli_offline(
    er_template: Path, tiny_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """TINY loaded into the active DuckDB, Neo4j URI pointing at a closed port."""
    path = tmp_path / "tiny.duckdb"
    shutil.copy(er_template, path)
    set_env(monkeypatch, {**tiny_env(), "AML__NEO4J__URI": OFFLINE_URI})
    return path


def test_ac1_cli_graph_help_lists_query_and_gds() -> None:
    result = cli("graph", "--help")
    assert result.exit_code == 0, result.output
    assert "query" in result.stdout
    assert "gds" in result.stdout


def test_ac1_cli_gds_without_neo4j_fails_and_writes_nothing(cli_offline: Path) -> None:
    result = cli("graph", "gds")
    assert result.exit_code == 1, result.output
    assert "neo4j not available" in result.stderr
    with DuckDb(cli_offline) as db:
        assert int(db.query_df("SELECT COUNT(*) FROM gds_runs").iloc[0, 0]) == 0
