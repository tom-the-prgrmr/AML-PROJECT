"""Helpers for the Phase 6c tests (specs/trace-benchmark.md): lazy imports, SAMPLE, settings."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

import pandas as pd

from aml.common.config import Settings, load_settings
from aml.common.db import Database
from tests.graph.helpers import PATH_COLUMNS
from tests.neo4j_queries.helpers import (
    OFFLINE_URI,
    cli,
    graph_audit,
    mod,
    neo_settings,
    run_sync,
    set_env,
)

__all__ = [
    "OFFLINE_URI",
    "REPO",
    "TIMING_FIELDS",
    "bench_settings",
    "by_hop_method",
    "cli",
    "empty_paths",
    "graph_audit",
    "make_sample",
    "mod",
    "neo_settings",
    "run_bench",
    "run_sync",
    "set_env",
    "stable_fields",
]

REPO = Path(__file__).resolve().parents[2]
TIMING_FIELDS = ("seconds", "median_ms", "p95_ms", "min_ms", "max_ms")


def bench_settings(results_dir: Path, **env: str) -> Settings:
    """OFFLINE settings of the spec: DuckDB, closed Neo4j port, 5 runs, results in a tmp dir."""
    return load_settings(
        environ={
            "DB_BACKEND": "duckdb",
            "AML__NEO4J__URI": OFFLINE_URI,
            "AML__BENCH__RUNS": "5",
            "AML__BENCH__RESULTS_DIR": str(results_dir),
            **env,
        }
    )


def run_bench(db: Database, settings: Settings, **kw: Any) -> Any:
    return mod("aml.graph.bench.runner").run_bench(db, settings, **kw)


def by_hop_method(result: Any) -> dict[tuple[int, str], Any]:
    return {(c.hops, c.method): c for c in result.cells}


def stable_fields(cell: Any) -> dict[str, Any]:
    """Every field of a cell except the timings."""
    return {f.name: getattr(cell, f.name) for f in fields(cell) if f.name not in TIMING_FIELDS}


def empty_paths() -> pd.DataFrame:
    """An empty answer with the PATH_COLUMNS shape."""
    frame = pd.DataFrame({c: pd.Series([], dtype=object) for c in PATH_COLUMNS})
    frame["hop"] = frame["hop"].astype("int64")
    frame["amount_vnd"] = frame["amount_vnd"].astype("int64")
    frame["is_cycle"] = frame["is_cycle"].astype(bool)
    return frame


def make_sample() -> Any:
    """SAMPLE of the spec: four cells at (A1, 720, 6) of a `small` / `oracle` run."""
    model = mod("aml.graph.bench.model")

    def cell(method: str, status: str, **kw: Any) -> Any:
        base: dict[str, Any] = {
            "method": method,
            "account": "A1",
            "hours": 720,
            "hops": 6,
            "status": status,
            "reason": None,
            "exact": True,
            "seconds": (),
            "median_ms": None,
            "p95_ms": None,
            "min_ms": None,
            "max_ms": None,
            "n_paths": None,
            "n_accounts": None,
            "n_cycles": None,
            "query_lines": None,
        }
        return model.BenchCell(**{**base, **kw})

    cells = [
        cell(
            "cte_raw",
            "ok",
            seconds=(0.4, 0.5, 0.6, 0.7, 0.8),
            median_ms=600.0,
            p95_ms=780.0,
            min_ms=400.0,
            max_ms=800.0,
            n_paths=22394,
            n_accounts=300,
            n_cycles=40,
            query_lines=30,
        ),
        cell(
            "cte_edge",
            "ok",
            exact=False,
            seconds=(0.004,) * 5,
            median_ms=4.0,
            p95_ms=4.0,
            min_ms=4.0,
            max_ms=4.0,
            n_paths=27,
            n_accounts=20,
            n_cycles=0,
            query_lines=38,
        ),
        cell("pgq", "error", reason="TraceError: more than 100000 paths"),
        cell("neo4j", "skipped", reason="neo4j not available"),
    ]
    meta: dict[str, Any] = {
        "schema": "bench/v1",
        "profile": "small",
        "backend": "oracle",
        "command": "aml bench",
        "started_at": "2026-10-13T08:00:00+00:00",
        "total_seconds": 12.5,
        "git_commit": "abc1234",
        "versions": {
            "python": "3.11.9",
            "aml": "0.1.0",
            "driver": "oracledb 3.0.6",
            "server": "23",
        },
        "machine": {"platform": "Windows-11", "processor": "x86_64", "cpu_count": 12},
        "dataset": {"customers": 10, "accounts": 20, "transactions": 300, "transfers": 250},
        "params": {
            "hops": [6],
            "hours": [720],
            "runs": 5,
            "warmup_runs": 1,
            "accounts": ["A1"],
            "picked": True,
        },
        "trace": {"max_paths": 100000, "edge_min_amount_vnd": 0, "edge_top_k": 0},
        "read_timeout_seconds": 60,
        "sync": None,
    }
    return model.BenchResult(meta=meta, cells=cells)
