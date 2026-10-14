"""Which trace methods can run right now, and if not, why (for the UI method selector)."""

from __future__ import annotations

from dataclasses import dataclass

from aml.common.config import Settings
from aml.common.db import Database
from aml.common.services import neo4j_status, oracle_status
from aml.graph.model import TraceMethod, TraceUnavailableError
from aml.graph.trace import METHODS

LABELS = {
    "cte_raw": "CTE (raw transactions)",
    "cte_edge": "CTE (daily edges, approximate)",
    "pgq": "SQL property graph (Oracle)",
    "neo4j": "Neo4j (Cypher)",
}


@dataclass(frozen=True)
class MethodAvailability:
    method: str
    label: str
    exact: bool
    uses_filters: bool
    available: bool
    reason: str | None


def _backend_reason(method: TraceMethod, db: Database, settings: Settings) -> str | None:
    if db.backend in method.backends:
        return None
    if settings.db.backend == "oracle" and "oracle" in method.backends:
        return f"oracle not available: {oracle_status(settings).detail}"
    return f"method {method.name} is Oracle only; backend is {db.backend}"


def _neo4j_reason(method: TraceMethod, db: Database, settings: Settings) -> str | None:
    status = neo4j_status(settings)
    if not status.up:
        return status.detail
    if method.prepare is None:
        return None
    try:
        method.prepare(db, settings)
    except TraceUnavailableError as exc:
        return str(exc)
    return None


def _reason(method: TraceMethod, db: Database, settings: Settings) -> str | None:
    if method.name == "neo4j":
        return _neo4j_reason(method, db, settings)
    return _backend_reason(method, db, settings)


def trace_methods(db: Database, settings: Settings) -> tuple[MethodAvailability, ...]:
    """One entry per registered method, in registry order. Probes are not cached."""
    result = []
    for name, method in list(METHODS.items()):
        reason = _reason(method, db, settings)
        result.append(
            MethodAvailability(
                method=name,
                label=LABELS.get(name, name),
                exact=method.exact,
                uses_filters=method.uses_filters,
                available=reason is None,
                reason=reason,
            )
        )
    return tuple(result)
