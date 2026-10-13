"""AC2 for specs/neo4j-queries.md: freshness check and failures without Neo4j (no services)."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb, ServiceUnavailableError
from tests.network.helpers import has

from .helpers import OFFLINE_URI, cli, graph_audit, mod, query, set_env, trace

WATERMARK = datetime(2026, 3, 2, 10, 0, 1)
RND = "A8201784530"


def _stale() -> Any:
    return mod("aml.graph.neo4j.session").StaleGraphError


def test_ac2_check_fresh_messages_in_order() -> None:
    session = mod("aml.graph.neo4j.session")
    assert issubclass(session.StaleGraphError, mod("aml.graph.neo4j.guard").GraphError)
    with pytest.raises(session.StaleGraphError, match="graph not synced: run aml graph sync"):
        session.check_fresh(None, "duckdb", 0, 0)
    with pytest.raises(session.StaleGraphError) as err:
        session.check_fresh((WATERMARK, "oracle"), "duckdb", 12, 12)
    assert "graph was synced from oracle but the database is duckdb" in str(err.value)
    assert "--full" in str(err.value)
    with pytest.raises(
        session.StaleGraphError, match=r"graph is out of sync \(12 of 13 transfers\)"
    ):
        session.check_fresh((WATERMARK, "duckdb"), "duckdb", 12, 13)
    assert session.check_fresh((WATERMARK, "duckdb"), "duckdb", 12, 12) is None


def test_ac2_trace_without_neo4j_is_unavailable(mini_t: DuckDb, offline: Settings) -> None:
    unavailable = mod("aml.graph.model").TraceUnavailableError
    with pytest.raises(unavailable, match="neo4j not available"):
        trace(mini_t, offline, "A", method="neo4j", hops=4, hours=24)


def test_ac2_invalid_input_wins_over_the_connection(mini_t: DuckDb, offline: Settings) -> None:
    model = mod("aml.graph.model")
    with pytest.raises(model.TraceError, match="hops") as err:
        trace(mini_t, offline, "A", method="neo4j", hops=7)
    assert not isinstance(err.value, model.TraceUnavailableError)


def test_ac2_unknown_method_lists_four_methods(mini_t: DuckDb, offline: Settings) -> None:
    with pytest.raises(mod("aml.graph.model").TraceError, match="cte_raw, cte_edge, pgq, neo4j"):
        trace(mini_t, offline, "A", method="bfs")


def test_ac2_run_query_errors_and_no_audit(mini_t: DuckDb, offline: Settings) -> None:
    queries = mod("aml.graph.neo4j.queries")
    with pytest.raises(queries.QueryError):
        query(mini_t, offline, "nope")
    with pytest.raises(ServiceUnavailableError):
        query(mini_t, offline, "cycles")
    assert graph_audit(mini_t).empty
    assert trace(mini_t, offline, "A", hops=4, hours=24).n_paths == 9


# ---------------------------------------------------------------------------------- CLI
@pytest.fixture
def cli_offline(
    er_template: Path, tiny_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """TINY loaded into the active DuckDB, Neo4j URI pointing at a closed port."""
    path = tmp_path / "tiny.duckdb"
    shutil.copy(er_template, path)
    set_env(monkeypatch, {**tiny_env(), "AML__NEO4J__URI": OFFLINE_URI})
    return path


def test_ac2_cli_trace_method_all_skips_pgq_and_neo4j(cli_offline: Path) -> None:
    result = cli("trace", "--account", RND, "--hops", "4", "--hours", "168", "--method", "all")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert len([ln for ln in lines if has(ln, "method=cte_raw")]) == 1
    assert len([ln for ln in lines if has(ln, "method=cte_edge")]) == 1
    assert len([ln for ln in lines if "method=pgq skipped: Oracle only" in ln]) == 1
    assert (
        len([ln for ln in lines if ln.startswith("method=neo4j skipped: neo4j not available")]) == 1
    )


def test_ac2_cli_trace_method_neo4j_exits_2(cli_offline: Path) -> None:
    result = cli("trace", "--account", RND, "--method", "neo4j")
    assert result.exit_code == 2, result.output
    assert "neo4j not available" in result.stderr


def test_ac2_cli_graph_query_failures(cli_offline: Path) -> None:
    result = cli("graph", "query", "cycles")
    assert result.exit_code == 1, result.output
    assert "neo4j not available" in result.stderr

    result = cli("graph", "query", "nope")
    assert result.exit_code == 2, result.output
    assert "shared_cluster" in result.stderr

    result = cli("graph", "query", "shared_cluster")
    assert result.exit_code == 2, result.output
    assert "customer" in result.stderr


def test_ac2_cli_graph_help() -> None:
    result = cli("graph", "--help")
    assert result.exit_code == 0, result.output
    for word in ("sync", "status", "query"):
        assert word in result.stdout
