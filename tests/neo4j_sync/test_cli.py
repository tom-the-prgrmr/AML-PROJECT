"""AC9 for specs/neo4j-sync.md: `aml graph sync` / `aml graph status` (DuckDB, TINY).

Output conventions chosen by the tests where the spec leaves the exact spacing open:
  summary line   ``run_id=1 mode=FULL source=duckdb since=- watermark=2026-06-30T21:53:57
                 nodes=2383 rels=8583 pruned=0 swept=0 lag_before_s=- lag_after_s=0 in_sync=True``
  per kind line  ``Customer sent=273 graph=273``
  status line    ``watermark=... source=duckdb last_run_id=2 lag_s=0`` then ``Customer 273``
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aml.common.config import get_settings
from aml.common.db import DuckDb
from tests.network.helpers import has, lines_for

from .conftest import Neo
from .helpers import KEYS_11, OFFLINE_URI, count, graph_audit, mod


def _cli(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, list(args))


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def _query(path: Path, sql: str) -> int:
    with DuckDb(path) as db:
        return int(db.query_df(sql).iloc[0, 0])


@pytest.fixture
def tiny_cli(
    er_template: Path, tiny_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """TINY after `aml load` and `aml er`, configured as the active database."""
    path = tmp_path / "tiny.duckdb"
    shutil.copy(er_template, path)
    _set_env(monkeypatch, tiny_env())
    return path


def _kind_lines(lines: list[str], marker: str) -> dict[str, list[str]]:
    return {name: lines_for(lines, name, marker) for name in KEYS_11}


def test_ac9_without_neo4j_sync_and_status_fail_cleanly(
    tiny_cli: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, {"AML__NEO4J__URI": OFFLINE_URI})
    result = _cli("graph", "sync")
    assert result.exit_code == 1, result.output
    assert "neo4j not available" in result.stderr
    assert _query(tiny_cli, "SELECT COUNT(*) FROM graph_sync_runs") == 0
    assert _query(tiny_cli, "SELECT COUNT(*) FROM audit_log WHERE module = 'graph'") == 0

    status = _cli("graph", "status")
    assert status.exit_code == 1, status.output
    assert "neo4j not available" in status.stderr


def test_ac9_graph_help_lists_commands_and_bench_stays_a_stub() -> None:
    result = _cli("graph", "--help")
    assert result.exit_code == 0, result.output
    assert "sync" in result.stdout
    assert "status" in result.stdout
    assert "Phase 6" not in result.stdout
    bench = _cli("bench")
    assert bench.exit_code == 1
    assert "Phase 6" in bench.stderr


def test_ac9_sync_without_load_fails_cleanly(
    tiny_env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, {**tiny_env(), "AML__NEO4J__URI": OFFLINE_URI})
    with DuckDb(tmp_path / "tiny.duckdb") as db:
        mod("aml.dba.schema").apply_schema(db)
    result = _cli("graph", "sync")
    assert result.exit_code == 1, result.output
    assert "run `aml load` first" in result.stderr


@pytest.mark.neo4j
def test_ac9_status_before_any_sync_exits_1(tiny_cli: Path, neo: Neo) -> None:
    result = _cli("graph", "status")
    assert result.exit_code == 1, result.output
    assert "graph not synced: run aml graph sync" in result.stderr


@pytest.mark.neo4j
def test_ac9_sync_full_then_incremental_then_status(tiny_cli: Path, neo: Neo) -> None:
    first = _cli("graph", "sync", "--full")
    assert first.exit_code == 0, first.output
    lines = first.stdout.splitlines()
    summary = [ln for ln in lines if "run_id=1" in ln]
    tokens = (
        "run_id=1",
        "mode=FULL",
        "source=duckdb",
        "since=-",
        "watermark=2026-06-30T21:53:57",
        "nodes=2383",
        "rels=8583",
        "pruned=0",
        "swept=0",
        "lag_before_s=-",
        "lag_after_s=0",
        "in_sync=True",
    )
    assert len(summary) == 1, summary
    assert all(has(summary[0], t) for t in tokens), summary[0]

    kinds = _kind_lines(lines, "sent=")
    assert all(len(v) == 1 for v in kinds.values()), kinds
    positions = [lines.index(kinds[name][0]) for name in KEYS_11]
    assert positions == sorted(positions)
    assert has(kinds["Customer"][0], "sent=273") and has(kinds["Customer"][0], "graph=273")
    assert has(kinds["Account"][0], "sent=1314") and has(kinds["Account"][0], "graph=1314")
    assert has(kinds["TRANSFERRED_TO"][0], "sent=3651")
    assert has(kinds["TRANSFERRED_TO"][0], "graph=3651")

    audit_after_sync = _query(tiny_cli, "SELECT COUNT(*) FROM audit_log WHERE module = 'graph'")

    second = _cli("graph", "sync")
    assert second.exit_code == 0, second.output
    lines = second.stdout.splitlines()
    summary = [ln for ln in lines if "run_id=2" in ln]
    tokens = (
        "run_id=2",
        "mode=INCREMENTAL",
        "since=2026-06-30T20:53:57",
        "lag_before_s=0",
        "in_sync=True",
    )
    assert len(summary) == 1, summary
    assert all(has(summary[0], t) for t in tokens), summary[0]
    kinds = _kind_lines(lines, "sent=")
    assert has(kinds["Account"][0], "sent=533") and has(kinds["Account"][0], "graph=1314")
    assert has(kinds["TRANSFERRED_TO"][0], "sent=1") and has(
        kinds["TRANSFERRED_TO"][0], "graph=3651"
    )
    assert has(kinds["SENT_TO"][0], "sent=19") and has(kinds["SENT_TO"][0], "graph=3575")

    audit_before_status = _query(tiny_cli, "SELECT COUNT(*) FROM audit_log WHERE module = 'graph'")
    assert audit_before_status == audit_after_sync + 1
    runs_before_status = _query(tiny_cli, "SELECT COUNT(*) FROM graph_sync_runs")

    status = _cli("graph", "status")
    assert status.exit_code == 0, status.output
    out = status.stdout.splitlines()
    head = [ln for ln in out if "watermark=" in ln]
    assert len(head) == 1, head
    for token in ("watermark=2026-06-30T21:53:57", "source=duckdb", "last_run_id=2", "lag_s=0"):
        assert has(head[0], token), head[0]
    assert ["Customer", "273"] in [ln.split() for ln in out]
    assert ["SENT_TO", "3575"] in [ln.split() for ln in out]

    assert (
        _query(tiny_cli, "SELECT COUNT(*) FROM audit_log WHERE module = 'graph'")
        == audit_before_status
    )
    assert _query(tiny_cli, "SELECT COUNT(*) FROM graph_sync_runs") == runs_before_status == 2
    with DuckDb(tiny_cli) as db:
        assert count(db, "graph_sync_runs") == 2
        assert len(graph_audit(db, "decision = 'SYNCED'")) == 2
