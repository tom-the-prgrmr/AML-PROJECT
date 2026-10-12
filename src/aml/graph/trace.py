"""Fund-flow tracing: follow money out of one account, N hops within T hours.

Methods share one answer shape (``PATH_COLUMNS``) and live in the ``METHODS`` registry, so
Phase 6 can add a Neo4j method with ``register_method``. ``trace`` validates the request
before touching the database, runs the method, and writes one ``TRACED`` audit row.
"""

from __future__ import annotations

import time
from datetime import datetime

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.model import (
    PATH_COLUMNS,
    PATH_SEPARATOR,
    TraceError,
    TraceMethod,
    TraceRequest,
    TraceResult,
)
from aml.graph.queries import count_query_lines, pgq_query_text, pgq_run, sql_method

__all__ = [
    "METHODS",
    "PATH_COLUMNS",
    "PATH_SEPARATOR",
    "TraceError",
    "TraceMethod",
    "TraceRequest",
    "TraceResult",
    "register_method",
    "trace",
]

AUDIT_MODULE = "graph"

METHODS: dict[str, TraceMethod] = {}


def register_method(method: TraceMethod) -> None:
    METHODS[method.name] = method


register_method(sql_method("cte_raw", exact=True, uses_filters=False))
register_method(sql_method("cte_edge", exact=False, uses_filters=True))
register_method(
    TraceMethod(
        name="pgq",
        backends=frozenset({"oracle"}),
        exact=True,
        run=pgq_run,
        query_text=pgq_query_text,
    )
)


def _resolve(
    db: Database,
    settings: Settings,
    account_id: str,
    method: str,
    hops: int | None,
    hours: int | None,
    since: datetime | None,
    min_amount_vnd: int | None,
    top_k: int | None,
) -> tuple[TraceMethod, TraceRequest]:
    """Validate the inputs and fill the gaps from config. Never touches the database."""
    cfg = settings.trace
    if method not in METHODS:
        raise TraceError(f"unknown method {method!r}; choose one of: {', '.join(METHODS)}")
    if not account_id or PATH_SEPARATOR in account_id:
        raise TraceError(f"account_id must be non-empty and must not contain {PATH_SEPARATOR!r}")
    hops = cfg.default_hops if hops is None else hops
    if not 1 <= hops <= cfg.max_hops:
        raise TraceError(f"hops must be between 1 and {cfg.max_hops}, got {hops}")
    hours = cfg.default_hours if hours is None else hours
    if not 1 <= hours <= cfg.max_hours:
        raise TraceError(f"hours must be between 1 and {cfg.max_hours}, got {hours}")
    min_amount_vnd = cfg.edge_min_amount_vnd if min_amount_vnd is None else min_amount_vnd
    top_k = cfg.edge_top_k if top_k is None else top_k
    if min_amount_vnd < 0:
        raise TraceError(f"min_amount_vnd must be >= 0, got {min_amount_vnd}")
    if top_k < 0:
        raise TraceError(f"top_k must be >= 0, got {top_k}")
    chosen = METHODS[method]
    if db.backend not in chosen.backends:
        raise TraceError(f"method {method} is Oracle only; backend is {db.backend}")
    if not chosen.uses_filters:  # ignored by this method: do not report values it never used
        min_amount_vnd, top_k = 0, 0
    return chosen, TraceRequest(account_id, hops, hours, since, min_amount_vnd, top_k)


def trace(
    db: Database,
    settings: Settings,
    account_id: str,
    *,
    method: str = "cte_raw",
    hops: int | None = None,
    hours: int | None = None,
    since: datetime | None = None,
    min_amount_vnd: int | None = None,
    top_k: int | None = None,
    actor: str | None = None,
    record_audit: bool = True,
) -> TraceResult:
    """Trace outgoing money from ``account_id``; raise ``TraceError`` for bad input or overflow."""
    chosen, request = _resolve(
        db, settings, account_id, method, hops, hours, since, min_amount_vnd, top_k
    )
    started = time.perf_counter()
    paths = chosen.run(db, settings, request)
    seconds = time.perf_counter() - started
    max_paths = settings.trace.max_paths
    if len(paths) > max_paths:
        raise TraceError(
            f"trace of {account_id} returned more than {max_paths} paths; "
            "lower hops or hours, or narrow it with since"
        )
    cycle = paths["is_cycle"]
    result = TraceResult(
        request=request,
        method=chosen.name,
        backend=db.backend,
        paths=paths,
        n_paths=len(paths),
        n_accounts=int(paths.loc[~cycle, "account_id"].nunique()),
        n_cycles=int(cycle.sum()),
        seconds=seconds,
        query_lines=count_query_lines(chosen.query_text(db.backend, request)),
    )
    if record_audit:
        _record(db, settings, result, actor)
    return result


def _record(db: Database, settings: Settings, result: TraceResult, actor: str | None) -> None:
    r = result.request
    audit(
        db,
        module=AUDIT_MODULE,
        entity_type="account",
        entity_id=r.account_id,
        decision="TRACED",
        reason=(
            f"{result.method} on {result.backend}: followed money out of {r.account_id} "
            f"up to {r.hops} hops within {r.hours} hours; found {result.n_paths} paths "
            f"to {result.n_accounts} accounts, {result.n_cycles} hops closing a cycle"
        ),
        version=f"trace/{result.method}",
        actor=actor or settings.audit.system_actor,
        details={
            "method": result.method,
            "backend": result.backend,
            "hops": r.hops,
            "hours": r.hours,
            "since": r.since.isoformat() if r.since else None,
            "min_amount_vnd": r.min_amount_vnd,
            "top_k": r.top_k,
            "paths": result.n_paths,
            "accounts": result.n_accounts,
            "cycles": result.n_cycles,
        },
    )
