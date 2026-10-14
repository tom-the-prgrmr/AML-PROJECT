"""Reads behind the trace endpoints: run a trace and map its errors to API errors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aml.api.errors import ApiError
from aml.api.paging import check_offset, resolve_limit
from aml.api.values import iso_seconds, plain
from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.model import PATH_COLUMNS, TraceError, TraceUnavailableError
from aml.graph.trace import METHODS, trace


def methods_meta(db: Database, settings: Settings) -> dict[str, Any]:
    cfg = settings.trace
    return {
        "backend": db.backend,
        "default_method": "cte_raw",
        "default_hops": cfg.default_hops,
        "default_hours": cfg.default_hours,
        "max_hops": cfg.max_hops,
        "max_hours": cfg.max_hours,
    }


def _api_error(exc: TraceError, method: str, db: Database) -> ApiError:
    chosen = METHODS.get(method)
    wrong_backend = chosen is not None and db.backend not in chosen.backends
    if isinstance(exc, TraceUnavailableError) or wrong_backend:
        return ApiError(503, "unavailable", str(exc))
    return ApiError(422, "invalid_request", str(exc))


def run_trace(
    db: Database,
    settings: Settings,
    account_id: str,
    *,
    actor: str,
    method: str,
    hops: int | None,
    hours: int | None,
    since: datetime | None,
    min_amount_vnd: int | None,
    top_k: int | None,
    limit: int | None,
    offset: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    limit = resolve_limit(settings, limit)  # before trace(): it writes the audit row
    check_offset(offset)
    try:
        result = trace(
            db,
            settings,
            account_id,
            method=method,
            hops=hops,
            hours=hours,
            since=since,
            min_amount_vnd=min_amount_vnd,
            top_k=top_k,
            actor=actor,
        )
    except TraceError as exc:
        raise _api_error(exc, method, db) from exc
    page = result.paths[PATH_COLUMNS].iloc[offset : offset + limit]
    rows = [_row(record) for record in page.to_dict("records")]
    req = result.request
    meta = {
        "method": result.method,
        "backend": result.backend,
        "exact": METHODS[result.method].exact,
        "account_id": req.account_id,
        "hops": req.hops,
        "hours": req.hours,
        "since": iso_seconds(req.since),
        "min_amount_vnd": req.min_amount_vnd,
        "top_k": req.top_k,
        "n_paths": result.n_paths,
        "n_accounts": result.n_accounts,
        "n_cycles": result.n_cycles,
        "seconds": float(result.seconds),
        "query_lines": result.query_lines,
        "total": result.n_paths,
        "limit": limit,
        "offset": offset,
    }
    return rows, meta


def _row(record: dict[str, Any]) -> dict[str, Any]:
    row = {k: plain(v) for k, v in record.items()}
    row["first_ts"] = iso_seconds(row["first_ts"])
    row["last_ts"] = iso_seconds(row["last_ts"])
    row["is_cycle"] = bool(row["is_cycle"])
    return row
