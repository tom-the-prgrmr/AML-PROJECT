"""The five investigation queries on the Neo4j projection (``aml graph query``).

Every query is one ``.cypher`` file run through the guarded READ path. Thresholds come from
config, the graph must match its source (`require_fresh`), and nothing is written to Neo4j or
raised as an alert: a successful call only leaves one ``QUERIED`` audit row.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from typing import Any

import pandas as pd

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.neo4j.client import load_statements, run_read_file
from aml.graph.neo4j.guard import GraphError
from aml.graph.neo4j.session import require_fresh, shared_driver
from aml.graph.queries import count_query_lines

AUDIT_MODULE = "graph"
QUERY_VERSION = "query/v1"

QUERY_NAMES = ("cycles", "shared_attributes", "shared_cluster", "fan_in", "fan_out")
_FAN_COLUMNS = [
    "account_id",
    "window_start",
    "window_end",
    "counterparties",
    "transfers",
    "total_vnd",
]
QUERY_COLUMNS: dict[str, list[str]] = {
    "cycles": ["length", "path", "step_path", "first_ts", "last_ts", "first_vnd", "last_vnd"],
    "shared_attributes": ["kind", "key", "customers", "customer_ids"],
    "shared_cluster": ["customer", "distance", "via", "accounts"],
    "fan_in": list(_FAN_COLUMNS),
    "fan_out": list(_FAN_COLUMNS),
}
_TAKES_ACCOUNT = {"cycles", "fan_in", "fan_out"}
_TAKES_CUSTOMER = {"shared_attributes", "shared_cluster"}


class QueryError(GraphError):
    """Unknown query, parameter it does not take, or a result larger than ``max_rows``."""


@dataclass(frozen=True)
class QueryResult:
    name: str
    params: dict[str, Any]  # exactly what was sent to Neo4j
    rows: pd.DataFrame  # columns = QUERY_COLUMNS[name], ordered by the file's ORDER BY
    n_rows: int
    seconds: float
    query_lines: int


def _cutoff(as_of: date) -> datetime:
    return datetime.combine(as_of + timedelta(days=1), dtime.min)


def _config_params(name: str, settings: Settings, as_of: date) -> dict[str, Any]:
    if name == "cycles":
        cfg = settings.network.cycles
        return {
            "min_length": cfg.min_length,
            "max_length": cfg.max_length,
            "window_hours": cfg.window_hours,
            "min_amount": cfg.min_amount_vnd,
            "min_amount_ratio": cfg.min_amount_ratio,
            "cutoff": _cutoff(as_of),
        }
    if name in _TAKES_CUSTOMER:
        return {
            "max_customers_per_value": settings.network.shared_attributes.max_customers_per_value
        }
    fan = settings.monitoring.fan_in_out
    return {
        "window_days": fan.window_days,
        "min_counterparties": fan.min_counterparties,
        "min_total_vnd": fan.min_total_vnd,
        "cutoff": _cutoff(as_of),
    }


def query_params(
    name: str,
    settings: Settings,
    *,
    account: str | None = None,
    customer: str | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Build the parameters of one query from config; pure Python, raises `QueryError`."""
    if name not in QUERY_NAMES:
        raise QueryError(f"unknown query {name!r}; choose one of: {', '.join(QUERY_NAMES)}")
    if account is not None and name not in _TAKES_ACCOUNT:
        raise QueryError(f"query {name} does not take --account (it takes --customer)")
    if customer is not None and name not in _TAKES_CUSTOMER:
        raise QueryError(f"query {name} does not take --customer (it takes --account)")
    if name == "shared_cluster" and not customer:
        raise QueryError("query shared_cluster needs --customer (a golden customer id)")
    params = _config_params(name, settings, as_of or settings.data.reference_date)
    if name in _TAKES_ACCOUNT:
        params["account"] = account
    else:
        params["customer"] = customer
    params["row_limit"] = settings.graph_queries.max_rows + 1
    return params


def _json_params(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in params.items()}


def run_query(
    db: Database,
    settings: Settings,
    name: str,
    *,
    account: str | None = None,
    customer: str | None = None,
    as_of: date | None = None,
    actor: str | None = None,
    record_audit: bool = True,
) -> QueryResult:
    """Run one named query on the projection; refuses a stale graph and oversized results."""
    params = query_params(name, settings, account=account, customer=customer, as_of=as_of)
    driver = shared_driver(settings)  # ServiceUnavailableError is the caller's to handle
    require_fresh(driver, db, settings)
    file = f"queries/{name}.cypher"
    started = time.perf_counter()
    frame = run_read_file(driver, settings, file, params)
    seconds = time.perf_counter() - started
    max_rows = settings.graph_queries.max_rows
    if len(frame) > max_rows:
        raise QueryError(
            f"query {name} returned more than {max_rows} rows; narrow it with "
            "--account / --customer / --as-of"
        )
    rows = frame[QUERY_COLUMNS[name]].reset_index(drop=True)
    result = QueryResult(
        name=name,
        params=params,
        rows=rows,
        n_rows=len(rows),
        seconds=seconds,
        query_lines=count_query_lines(load_statements(file)[0]),
    )
    if record_audit:
        audit(
            db,
            module=AUDIT_MODULE,
            entity_type="graph_query",
            entity_id=name,
            decision="QUERIED",
            reason=f"{name} on the Neo4j projection: {result.n_rows} row(s)",
            version=QUERY_VERSION,
            actor=actor or settings.audit.system_actor,
            details={"name": name, "params": _json_params(params), "rows": result.n_rows},
        )
    return result
