"""The ``neo4j`` trace method: the same answer as ``cte_raw``, read from the Neo4j projection.

``prepare`` (run by ``trace()`` before the clock starts) opens the shared driver and checks the
graph is fresh; ``run`` only queries. This module must not import ``aml.graph.trace``.
"""

from __future__ import annotations

import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database, ServiceUnavailableError
from aml.graph.model import TraceError, TraceMethod, TraceRequest, TraceUnavailableError
from aml.graph.neo4j.client import load_statements, run_read_file
from aml.graph.neo4j.guard import GraphError
from aml.graph.neo4j.session import StaleGraphError, require_fresh, shared_driver
from aml.graph.queries import normalise

TRACE_FILE = "queries/trace.cypher"


def run(db: Database, settings: Settings, request: TraceRequest) -> pd.DataFrame:
    params = {
        "account": request.account_id,
        "hops": request.hops,
        "hours": request.hours,
        "since": request.since,
        "row_limit": settings.trace.max_paths + 1,
    }
    try:
        frame = run_read_file(shared_driver(settings), settings, TRACE_FILE, params)
    except ServiceUnavailableError as exc:
        raise TraceUnavailableError(f"neo4j not available: {exc}") from exc
    except GraphError as exc:  # e.g. the read timeout: a clean trace error, not a traceback
        raise TraceError(f"neo4j trace failed: {exc}") from exc
    return normalise(frame)


def prepare(db: Database, settings: Settings) -> None:
    try:
        require_fresh(shared_driver(settings), db, settings)
    except ServiceUnavailableError as exc:
        raise TraceUnavailableError(f"neo4j not available: {exc}") from exc
    except StaleGraphError as exc:
        raise TraceUnavailableError(str(exc)) from exc
    except GraphError as exc:  # the freshness check itself failed (e.g. timed out)
        raise TraceUnavailableError(f"neo4j graph check failed: {exc}") from exc


def query_text(backend: str, request: TraceRequest) -> str:
    return load_statements(TRACE_FILE)[0]


NEO4J_METHOD = TraceMethod(
    name="neo4j",
    backends=frozenset({"oracle", "duckdb"}),
    exact=True,
    run=run,
    query_text=query_text,
    uses_filters=False,
    prepare=prepare,
)
