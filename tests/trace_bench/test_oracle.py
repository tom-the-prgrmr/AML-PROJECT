"""AC7 for specs/trace-benchmark.md: all four methods on Oracle (TINY) with a Neo4j synced from it.

Needs Oracle, Neo4j, ORACLE_SYS_PASSWORD and ORACLE_DEMO_PASSWORD. Like the 6a / 6b-i Oracle tests
it reloads TINY into the schema owner and re-applies the grants.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import OracleDb

from .conftest import Neo
from .helpers import by_hop_method, graph_audit, mod, run_bench, run_sync

pytestmark = [pytest.mark.oracle, pytest.mark.neo4j]


@pytest.fixture
def oracle_settings() -> Settings:
    env = {
        **read_environ(),
        "DB_BACKEND": "oracle",
        "AML__BENCH__HOURS": "[720]",
        "AML__BENCH__RUNS": "5",
    }
    for name in ("ORACLE_SYS_PASSWORD", "ORACLE_DEMO_PASSWORD"):
        if not env.get(name):
            pytest.skip(f"{name} is not set in .env")
    return load_settings(environ=env)


def test_ac7_oracle_bench_runs_all_four_methods(
    neo: Neo, oracle_settings: Settings, tiny_parquet: Path, tmp_path: Path
) -> None:
    with OracleDb(oracle_settings) as odb:
        mod("aml.datagen.load").load_parquet(odb, tiny_parquet)
        mod("aml.entity_resolution.runner").run_er(odb, oracle_settings)
    mod("aml.dba.security").apply_security(oracle_settings)

    with OracleDb(oracle_settings) as odb:
        run_sync(odb, oracle_settings, full=True)
        where = "decision = 'BENCHMARKED' AND entity_id = 'small-oracle'"
        before = len(graph_audit(odb, where))
        result = run_bench(odb, oracle_settings)
        after = len(graph_audit(odb, where))

    assert result.meta["backend"] == "oracle"
    assert result.meta["profile"] == "small"
    assert result.meta["params"]["accounts"] == ["A7341585768"]
    assert len(result.cells) == 12
    assert [c.status for c in result.cells] == ["ok"] * 12, [c.reason for c in result.cells]

    cells = by_hop_method(result)
    for method in ("cte_raw", "pgq", "neo4j"):
        assert [cells[(h, method)].n_paths for h in (2, 4, 6)] == [92, 125, 125], method
    pgq_lines = [cells[(h, "pgq")].query_lines for h in (2, 4, 6)]
    assert pgq_lines[0] < pgq_lines[1] < pgq_lines[2]
    for method in ("neo4j", "cte_raw"):
        assert len({cells[(h, method)].query_lines for h in (2, 4, 6)}) == 1, method

    written = mod("aml.graph.bench.report").write_result(result, tmp_path)
    assert written == tmp_path / "bench_small_oracle.json"
    assert after == before + 1
