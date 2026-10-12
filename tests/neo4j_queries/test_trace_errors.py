"""Review follow-up for specs/neo4j-queries.md: a Neo4j failure during a trace is a trace error
with a clear message, never a raw driver / graph exception (no service needed)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from aml.cli import app
from aml.common.config import get_settings, load_settings
from aml.common.db import ServiceUnavailableError
from aml.graph.model import TraceError, TraceRequest, TraceUnavailableError
from aml.graph.neo4j import trace as neo4j_trace
from aml.graph.neo4j.client import QueryTimeoutError

REQUEST = TraceRequest(account_id="A1", hops=2, hours=24)


def _raise(exc: Exception):
    def boom(*args: object, **kwargs: object) -> None:
        raise exc

    return boom


@pytest.fixture
def no_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(neo4j_trace, "shared_driver", lambda settings: None)


def test_run_timeout_is_a_trace_error(no_driver: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        neo4j_trace, "run_read_file", _raise(QueryTimeoutError("query exceeded 60 s"))
    )
    with pytest.raises(TraceError, match="neo4j trace failed: query exceeded 60 s") as info:
        neo4j_trace.run(None, load_settings(environ={}), REQUEST)  # type: ignore[arg-type]
    assert not isinstance(info.value, TraceUnavailableError)


def test_run_lost_connection_is_unavailable(
    no_driver: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        neo4j_trace, "run_read_file", _raise(ServiceUnavailableError("lost the connection"))
    )
    with pytest.raises(TraceUnavailableError, match="neo4j not available: lost the connection"):
        neo4j_trace.run(None, load_settings(environ={}), REQUEST)  # type: ignore[arg-type]


def test_prepare_timeout_is_unavailable(no_driver: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        neo4j_trace, "require_fresh", _raise(QueryTimeoutError("query exceeded 60 s"))
    )
    with pytest.raises(TraceUnavailableError, match="neo4j graph check failed: query exceeded"):
        neo4j_trace.prepare(None, load_settings(environ={}))  # type: ignore[arg-type]


def test_cli_trace_timeout_exits_2_without_a_traceback(
    no_driver: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DB_BACKEND", "duckdb")
    monkeypatch.setenv("AML__DB__DUCKDB_PATH", str(tmp_path / "empty.duckdb"))
    get_settings.cache_clear()
    monkeypatch.setattr(neo4j_trace, "require_fresh", lambda driver, db, settings: None)
    monkeypatch.setattr(
        neo4j_trace, "run_read_file", _raise(QueryTimeoutError("query exceeded 60 s"))
    )
    result = CliRunner().invoke(app, ["trace", "--account", "A1", "--method", "neo4j"])
    assert result.exit_code == 2, result.output
    assert "neo4j trace failed: query exceeded 60 s" in result.stderr
    assert "Traceback" not in result.output
