"""AC2 and AC3 for specs/trace-benchmark.md: `run_bench` on MINI-T (DuckDB, Neo4j offline)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import (
    bench_settings,
    by_hop_method,
    empty_paths,
    graph_audit,
    mod,
    run_bench,
    stable_fields,
)

METHOD_ORDER = ["cte_raw", "cte_edge", "pgq", "neo4j"]
VOLATILE_META = ("started_at", "total_seconds")


def _audit_count(db: DuckDb) -> int:
    return int(db.query_df("SELECT COUNT(*) FROM audit_log").iloc[0, 0])


def _benchmarked(db: DuckDb) -> Any:
    return graph_audit(db, "decision = 'BENCHMARKED'")


# ---------------------------------------------------------------------------------- AC2
def test_ac2_meta_and_cell_layout(mini_t: DuckDb, tmp_path: Path) -> None:
    settings = bench_settings(tmp_path, AML__BENCH__HOURS="[24]")
    result = run_bench(mini_t, settings, profile="mini")
    meta = result.meta
    assert meta["schema"] == "bench/v1"
    assert meta["profile"] == "mini"
    assert meta["backend"] == "duckdb"
    assert meta["params"]["accounts"] == ["A"]
    assert meta["params"]["picked"] is True
    assert meta["params"]["runs"] == 5
    assert meta["dataset"]["transfers"] == 12
    assert meta["sync"] is None

    assert [(c.hops, c.method) for c in result.cells] == [
        (hops, method) for hops in (2, 4, 6) for method in METHOD_ORDER
    ]
    assert all(c.account == "A" and c.hours == 24 for c in result.cells)


def test_ac2_ok_cells_values(mini_t: DuckDb, tmp_path: Path) -> None:
    stats = mod("aml.graph.bench.stats")
    result = run_bench(mini_t, bench_settings(tmp_path, AML__BENCH__HOURS="[24]"), profile="mini")
    cells = by_hop_method(result)

    for method, exact, paths in (("cte_raw", True, (3, 9, 9)), ("cte_edge", False, (4, 11, 11))):
        for hops, n_paths in zip((2, 4, 6), paths, strict=True):
            cell = cells[(hops, method)]
            assert cell.status == "ok", (method, hops, cell.reason)
            assert cell.exact is exact
            assert cell.n_paths == n_paths
    raw = [cells[(h, "cte_raw")] for h in (2, 4, 6)]
    assert [c.n_accounts for c in raw] == [2, 6, 6]
    assert [c.n_cycles for c in raw] == [1, 3, 3]

    for cell in result.cells:
        if cell.status != "ok":
            continue
        assert len(cell.seconds) == 5
        assert all(s > 0 for s in cell.seconds)
        assert cell.median_ms == pytest.approx(stats.median(cell.seconds) * 1000)
        assert cell.p95_ms == pytest.approx(stats.percentile(cell.seconds, 95) * 1000)
        assert cell.min_ms <= cell.median_ms <= cell.p95_ms <= cell.max_ms
        assert cell.query_lines > 0


def test_ac2_skipped_cells(mini_t: DuckDb, tmp_path: Path) -> None:
    result = run_bench(mini_t, bench_settings(tmp_path, AML__BENCH__HOURS="[24]"), profile="mini")
    cells = by_hop_method(result)
    for hops in (2, 4, 6):
        assert cells[(hops, "pgq")].status == "skipped"
        assert cells[(hops, "pgq")].reason == "not available on duckdb"
        assert cells[(hops, "neo4j")].status == "skipped"
        assert "neo4j not available" in cells[(hops, "neo4j")].reason
    for cell in result.cells:
        if cell.status != "ok":
            assert cell.seconds == ()
            for name in ("median_ms", "p95_ms", "n_paths", "query_lines"):
                assert getattr(cell, name) is None, (cell.method, name)


def test_ac2_audit_row(mini_t: DuckDb, tmp_path: Path) -> None:
    before = _audit_count(mini_t)
    run_bench(mini_t, bench_settings(tmp_path, AML__BENCH__HOURS="[24]"), profile="mini")
    assert _audit_count(mini_t) == before + 1
    rows = _benchmarked(mini_t)
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["entity_type"] == "benchmark"
    assert row["entity_id"] == "mini-duckdb"
    assert row["version"] == "bench/v1"
    assert row["reason"] == (
        "trace benchmark on duckdb (mini): 6 cells ok, 6 skipped, 0 failed; 5 timed runs per cell"
    )
    assert row["details"]["ok"] == 6
    assert row["details"]["skipped"] == 6
    assert row["details"]["error"] == 0
    assert graph_audit(mini_t, "decision = 'TRACED'").empty


def test_ac2_profile_defaults_to_unknown(mini_t: DuckDb, tmp_path: Path) -> None:
    result = run_bench(mini_t, bench_settings(tmp_path, AML__BENCH__HOURS="[24]"))
    assert result.meta["profile"] == "unknown"


def test_ac2_write_and_read_round_trip(mini_t: DuckDb, tmp_path: Path) -> None:
    report = mod("aml.graph.bench.report")
    out = tmp_path / "out"
    out.mkdir()
    result = run_bench(mini_t, bench_settings(tmp_path, AML__BENCH__HOURS="[24]"), profile="mini")
    assert report.write_result(result, out) == out / "bench_mini_duckdb.json"
    back = report.read_results(out)
    assert len(back) == 1
    assert back[0].cells == result.cells
    assert back[0].meta == result.meta


def test_ac2_second_run_equals_first_except_timings(mini_t: DuckDb, tmp_path: Path) -> None:
    settings = bench_settings(tmp_path, AML__BENCH__HOURS="[24]")
    first = run_bench(mini_t, settings, profile="mini")
    second = run_bench(mini_t, settings, profile="mini")
    assert [stable_fields(c) for c in first.cells] == [stable_fields(c) for c in second.cells]
    keep = {k: v for k, v in first.meta.items() if k not in VOLATILE_META}
    assert keep == {k: v for k, v in second.meta.items() if k not in VOLATILE_META}


# ---------------------------------------------------------------------------------- AC3
def test_ac3_max_paths_makes_error_cells(mini_t: DuckDb, tmp_path: Path) -> None:
    settings = bench_settings(tmp_path, AML__BENCH__HOURS="[24]", AML__TRACE__MAX_PATHS="8")
    result = run_bench(mini_t, settings, profile="mini")
    cells = by_hop_method(result)
    assert cells[(2, "cte_raw")].status == "ok" and cells[(2, "cte_raw")].n_paths == 3
    assert cells[(2, "cte_edge")].status == "ok" and cells[(2, "cte_edge")].n_paths == 4
    for method in ("cte_raw", "cte_edge"):
        for hops in (4, 6):
            cell = cells[(hops, method)]
            assert cell.status == "error", (method, hops)
            assert cell.reason.startswith("TraceError:")
            assert "more than 8 paths" in cell.reason
            assert cell.seconds == ()
    assert "2 cells ok, 6 skipped, 4 failed" in _benchmarked(mini_t).iloc[-1]["reason"]


def test_ac3_a_failing_method_does_not_stop_the_run(
    mini_t: DuckDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    methods = mod("aml.graph.trace").METHODS

    def boom(*args: object, **kwargs: object) -> pd.DataFrame:
        raise RuntimeError("boom")

    monkeypatch.setitem(methods, "cte_edge", dataclasses.replace(methods["cte_edge"], run=boom))
    result = run_bench(mini_t, bench_settings(tmp_path, AML__BENCH__HOURS="[24]"), profile="mini")
    cells = by_hop_method(result)
    for hops in (2, 4, 6):
        assert cells[(hops, "cte_edge")].status == "error"
        assert cells[(hops, "cte_edge")].reason == "RuntimeError: boom"
    assert [cells[(h, "cte_raw")].status for h in (2, 4, 6)] == ["ok"] * 3
    assert [cells[(h, "cte_raw")].n_paths for h in (2, 4, 6)] == [3, 9, 9]


def test_ac3_warmup_and_timed_runs_are_counted(
    mini_t: DuckDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    methods = mod("aml.graph.trace").METHODS
    calls: list[int] = []

    def fake_run(*args: object, **kwargs: object) -> pd.DataFrame:
        calls.append(1)
        return empty_paths()

    monkeypatch.setitem(methods, "cte_raw", dataclasses.replace(methods["cte_raw"], run=fake_run))
    settings = bench_settings(
        tmp_path, AML__BENCH__HOURS="[24]", AML__BENCH__WARMUP_RUNS="2", AML__BENCH__RUNS="5"
    )
    result = run_bench(mini_t, settings, profile="mini")
    assert len(calls) == 21
    for hops in (2, 4, 6):
        cell = by_hop_method(result)[(hops, "cte_raw")]
        assert cell.status == "ok", cell.reason
        assert len(cell.seconds) == 5
        assert cell.n_paths == 0


def test_ac3_explicit_accounts_are_used_as_given(mini_t: DuckDb, tmp_path: Path) -> None:
    settings = bench_settings(tmp_path, AML__BENCH__HOURS="[24]", AML__BENCH__ACCOUNTS='["ZZZ"]')
    result = run_bench(mini_t, settings, profile="mini")
    assert result.meta["params"]["accounts"] == ["ZZZ"]
    assert result.meta["params"]["picked"] is False
    for hops in (2, 4, 6):
        cell = by_hop_method(result)[(hops, "cte_raw")]
        assert cell.account == "ZZZ"
        assert cell.status == "ok", cell.reason
        assert cell.n_paths == 0


def test_ac3_empty_database_raises_and_audits_nothing(duck: DuckDb, tmp_path: Path) -> None:
    mod("aml.dba.schema").apply_schema(duck)
    bench_error = mod("aml.graph.bench.model").BenchError
    with pytest.raises(bench_error, match="no account to benchmark"):
        run_bench(duck, bench_settings(tmp_path))
    assert _benchmarked(duck).empty
