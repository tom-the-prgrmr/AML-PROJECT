"""Run a trace query file on either backend and normalise the answer to one frame shape."""

from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database, split_oracle_script, sql_file
from aml.graph.model import PATH_COLUMNS, TraceMethod, TraceRequest

SORT_COLUMNS = ["hop", "path", "step_path"]
TEXT_COLUMNS = ["path", "account_id", "step_path"]
TIME_COLUMNS = ["first_ts", "last_ts"]
BIND = {"oracle": re.compile(r":([A-Za-z_]\w*)"), "duckdb": re.compile(r"\$([A-Za-z_]\w*)")}


def is_code_line(line: str) -> bool:
    s = line.strip()
    return bool(s) and not s.startswith("--")


def count_query_lines(sql: str) -> int:
    """Non-blank lines that are not ``--`` comments."""
    return sum(is_code_line(ln) for ln in sql.splitlines())


def load_query(name: str, backend: str) -> str:
    """Text of ``trace/<name>.sql`` as one executable statement (no ``/`` or ``;``)."""
    text = sql_file(f"trace/{name}.sql", backend).read_text(encoding="utf-8")
    if backend == "oracle":
        return split_oracle_script(text)[0]
    return text.strip().rstrip(";")


def bind_values(request: TraceRequest, row_limit: int) -> dict[str, Any]:
    return {
        "account": request.account_id,
        "hops": request.hops,
        "hours": request.hours,
        "days": math.ceil(request.hours / 24),
        "since": request.since,
        "min_amount": request.min_amount_vnd,
        "top_k": request.top_k,
        "row_limit": row_limit,
    }


def used_binds(sql: str, backend: str, values: dict[str, Any]) -> dict[str, Any]:
    """Only the binds named in the code lines: an unused bind is an error on both drivers."""
    code = "\n".join(ln for ln in sql.splitlines() if is_code_line(ln))
    names = set(BIND[backend].findall(code))
    return {k: v for k, v in values.items() if k in names}


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """One shape for Oracle and DuckDB: lower-case columns, PATH_COLUMNS order, fixed dtypes."""
    df = df.rename(columns=str.lower)[PATH_COLUMNS].copy()
    df["hop"] = df["hop"].astype("int64")
    df["amount_vnd"] = df["amount_vnd"].astype("int64")
    df["is_cycle"] = df["is_cycle"].map(lambda v: v in (True, "Y")).astype(bool)
    for col in TEXT_COLUMNS:
        df[col] = df[col].astype(str)
    for col in TIME_COLUMNS:
        df[col] = pd.to_datetime(df[col]).astype("datetime64[us]")
    # Sorted here, not by ORDER BY: Oracle's NLS_SORT may order text differently.
    return df.sort_values(SORT_COLUMNS, kind="stable").reset_index(drop=True)


def run_query(db: Database, settings: Settings, request: TraceRequest, name: str) -> pd.DataFrame:
    """Run ``trace/<name>.sql``, asking for max_paths + 1 rows so the caller can detect overflow."""
    sql = load_query(name, db.backend)
    values = bind_values(request, settings.trace.max_paths + 1)
    return normalise(db.query_df(sql, used_binds(sql, db.backend, values)))


def sql_method(name: str, *, exact: bool, uses_filters: bool) -> TraceMethod:
    """A method backed by ``trace/<name>.sql`` on both backends."""
    return TraceMethod(
        name=name,
        backends=frozenset({"oracle", "duckdb"}),
        exact=exact,
        run=lambda db, settings, request: run_query(db, settings, request, name),
        query_text=lambda backend, request: load_query(name, backend),
        uses_filters=uses_filters,
    )


def pgq_query_text(backend: str, request: TraceRequest) -> str:
    """The first ``hops`` GRAPH_TABLE blocks of pgq.sql (blocks are split by UNION ALL lines).

    The row cap is added here, not in the file, so that cutting blocks cannot drop it.
    """
    blocks = re.split(r"^\s*UNION ALL\s*$", load_query("pgq", backend), flags=re.MULTILINE)
    union = "\nUNION ALL\n".join(b.strip() for b in blocks[: request.hops])
    return f"SELECT * FROM (\n{union}\n)\nFETCH FIRST :row_limit ROWS ONLY"


def pgq_run(db: Database, settings: Settings, request: TraceRequest) -> pd.DataFrame:
    sql = pgq_query_text(db.backend, request)
    values = bind_values(request, settings.trace.max_paths + 1)
    return normalise(db.query_df(sql, used_binds(sql, db.backend, values)))
