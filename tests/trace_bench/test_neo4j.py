"""AC6 for specs/trace-benchmark.md: the `neo4j` cells against a real Neo4j (TINY in DuckDB)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aml.dba.edges import refresh_acct_edge_daily
from tests.graph.helpers import RND
from tests.neo4j_queries.helpers import Synced, synced_db
from tests.neo4j_sync.helpers import TINY_S11, s11
from tests.network.helpers import add_txns

from .helpers import by_hop_method, graph_audit, neo_settings, run_bench, run_sync

pytestmark = pytest.mark.neo4j

BENCH_ENV = {"AML__BENCH__HOURS": "[720]", "AML__BENCH__RUNS": "5"}


def _settings(**extra: str) -> Any:
    return neo_settings(**{**BENCH_ENV, **extra})


@pytest.fixture(scope="module")
def tiny(er_template: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Synced]:
    path = tmp_path_factory.mktemp("bench_tiny") / "tiny.duckdb"
    with synced_db(
        path, template=er_template, expect_graph=s11(*TINY_S11), settings=_settings()
    ) as env:
        yield env


def test_ac6_neo4j_cells_equal_cte_raw(tiny: Synced) -> None:
    result = run_bench(tiny.db, tiny.settings, profile="tiny")
    cells = by_hop_method(result)
    for hops, expected in zip((2, 4, 6), (92, 125, 125), strict=True):
        neo, raw = cells[(hops, "neo4j")], cells[(hops, "cte_raw")]
        assert neo.status == "ok", neo.reason
        assert neo.exact is True
        assert neo.n_paths == expected == raw.n_paths
        assert cells[(hops, "pgq")].status == "skipped"
    assert len({cells[(h, "neo4j")].query_lines for h in (2, 4, 6)}) == 1
    assert result.meta["sync"]["full_seconds"] > 0
    assert result.meta["sync"]["lag_after_seconds"] == 0
    rows = graph_audit(tiny.db, "decision = 'BENCHMARKED'")
    assert "9 cells ok, 3 skipped, 0 failed" in rows.iloc[-1]["reason"]
    assert graph_audit(tiny.db, "decision = 'TRACED'").empty


def test_ac6_out_of_sync_graph_skips_neo4j_cells(er_template: Path, tmp_path: Path) -> None:
    with synced_db(
        tmp_path / "tiny.duckdb",
        template=er_template,
        expect_graph=s11(*TINY_S11),
        settings=_settings(),
    ) as env:
        add_txns(env.db, [("ZZ-NEW-1", "2026-07-01 09:00:00", RND, "A3312263346", 1_000_000)])
        refresh_acct_edge_daily(env.db)
        result = run_bench(env.db, env.settings, profile="tiny")
        cells = by_hop_method(result)
        for hops in (2, 4, 6):
            assert cells[(hops, "neo4j")].status == "skipped"
            assert "graph is out of sync" in cells[(hops, "neo4j")].reason
            assert cells[(hops, "cte_raw")].status == "ok"
            assert cells[(hops, "cte_edge")].status == "ok"
        assert result.meta["sync"] is None
        run_sync(env.db, env.settings, full=True)


def _benchmark_transactions(driver: Any) -> list[str]:
    with driver.session() as session:
        rows = session.run("SHOW TRANSACTIONS YIELD currentQuery RETURN currentQuery").data()
    return [r["currentQuery"] for r in rows if "SHOW TRANSACTIONS" not in r["currentQuery"]]


def test_ac6_read_timeout_gives_failed_cells_and_leaves_no_transaction(tiny: Synced) -> None:
    slow = _settings(AML__NEO4J__READ_TIMEOUT_SECONDS="0.000001")
    result = run_bench(tiny.db, slow, profile="tiny")
    cells = by_hop_method(result)
    for hops in (2, 4, 6):
        neo = cells[(hops, "neo4j")]
        assert neo.status != "ok"
        assert neo.reason is not None
        assert cells[(hops, "cte_raw")].status == "ok"
    leftover: list[str] = _benchmark_transactions(tiny.driver)
    for _ in range(10):  # the server may need a moment to roll a cancelled query back
        if not leftover:
            break
        time.sleep(0.5)
        leftover = _benchmark_transactions(tiny.driver)
    assert leftover == []
