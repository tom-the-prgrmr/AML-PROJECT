"""Types shared by every trace method: request, method descriptor, result."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database

PATH_COLUMNS = [
    "hop",
    "path",
    "account_id",
    "step_path",
    "first_ts",
    "last_ts",
    "amount_vnd",
    "is_cycle",
]
PATH_SEPARATOR = ">"


class TraceError(RuntimeError):
    """The trace request is invalid or its answer is too large."""


@dataclass(frozen=True)
class TraceRequest:
    account_id: str
    hops: int
    hours: int
    since: datetime | None = None  # the first hop must have txn_ts >= since
    min_amount_vnd: int = 0  # cte_edge only
    top_k: int = 0  # cte_edge only; 0 = unlimited


@dataclass(frozen=True)
class TraceMethod:
    name: str  # "cte_raw" | "cte_edge" | "pgq" (Phase 6 adds "neo4j")
    backends: frozenset[str]  # Database backends the method runs on
    exact: bool  # True: same rows as cte_raw; False: approximate by day
    run: Callable[[Database, Settings, TraceRequest], pd.DataFrame]  # returns PATH_COLUMNS
    query_text: Callable[[str, TraceRequest], str]  # (backend, request) -> query that runs
    uses_filters: bool = False  # honours min_amount_vnd / top_k


@dataclass(frozen=True)
class TraceResult:
    request: TraceRequest
    method: str
    backend: str
    paths: pd.DataFrame  # PATH_COLUMNS, sorted by (hop, path, step_path)
    n_paths: int
    n_accounts: int  # distinct account_id on the rows with is_cycle = False
    n_cycles: int  # rows with is_cycle = True
    seconds: float  # query time
    query_lines: int  # non-blank, non-comment lines of the query that ran
