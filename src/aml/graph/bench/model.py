"""Types of a benchmark run: one ``BenchCell`` per (method, hops, T, account)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCHEMA = "bench/v1"
NOTE_APPROXIMATE = "approximate (daily edges, top-K): paths not comparable"
STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"  # the method cannot run here (wrong backend, service down, stale graph)
STATUS_ERROR = "error"  # the method ran and failed (too many paths, timeout, any exception)


class BenchError(RuntimeError):
    """The benchmark cannot start (e.g. no account to trace from)."""


@dataclass(frozen=True)
class BenchCell:
    method: str
    account: str
    hours: int
    hops: int
    status: str  # "ok" | "skipped" | "error"
    reason: str | None  # None when ok
    exact: bool
    seconds: tuple[float, ...]  # TraceResult.seconds of each timed run; empty unless ok
    median_ms: float | None
    p95_ms: float | None
    min_ms: float | None
    max_ms: float | None
    n_paths: int | None
    n_accounts: int | None
    n_cycles: int | None
    query_lines: int | None


@dataclass(frozen=True)
class BenchResult:
    meta: dict[str, Any]  # JSON types only (lists, not tuples), so a file reads back unchanged
    cells: list[BenchCell]
