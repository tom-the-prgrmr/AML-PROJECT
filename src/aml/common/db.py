"""Thin database abstraction over Oracle (system of record) and DuckDB (zero-setup fallback).

SQL lives in ``.sql`` files. ``sql_file(name)`` resolves ``sql/<backend>/<name>`` first and
falls back to ``sql/common/<name>`` for statements that are portable across both dialects.

Script conventions:
* DuckDB scripts: plain ``;``-terminated statements.
* Oracle scripts: SQL*Plus style - every statement (SQL or PL/SQL) ends with a line
  containing only ``/``. This keeps PL/SQL blocks unambiguous and lets the same file run
  in SQL*Plus / SQLcl unchanged.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from aml.common.config import PROJECT_ROOT, Settings, get_settings

log = logging.getLogger(__name__)

SQL_ROOT = PROJECT_ROOT / "sql"
Params = Mapping[str, Any] | Sequence[Any] | None


class ServiceUnavailableError(RuntimeError):
    """An optional external service (Oracle / Neo4j / Ollama) is not reachable."""


class Database(ABC):
    """Minimal interface every module uses; keeps business code backend-agnostic."""

    backend: str

    @abstractmethod
    def execute(self, sql: str, params: Params = None) -> None: ...

    @abstractmethod
    def query_df(self, sql: str, params: Params = None) -> pd.DataFrame: ...

    @abstractmethod
    def run_script(self, path: Path) -> int:
        """Run every statement in a script file; return the number of statements."""

    @abstractmethod
    def insert_df(self, table: str, df: pd.DataFrame) -> int:
        """Bulk-insert a DataFrame (column names must match the table); return row count."""

    @abstractmethod
    def close(self) -> None: ...

    def sql_file(self, name: str) -> Path:
        return sql_file(name, self.backend)

    def run_named_script(self, name: str) -> int:
        return self.run_script(self.sql_file(name))

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def sql_file(name: str, backend: str) -> Path:
    """Resolve a SQL file for a backend, falling back to the portable ``sql/common`` copy."""
    for candidate in (SQL_ROOT / backend / name, SQL_ROOT / "common" / name):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"SQL file {name!r} not found for backend {backend!r}")


def split_oracle_script(text: str) -> list[str]:
    """Split a SQL*Plus-style script on lines that contain only ``/``."""
    statements: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip() == "/":
            stmt = "\n".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
        else:
            buf.append(line)
    tail = "\n".join(buf).strip()
    if tail and not all(_is_comment_or_blank(ln) for ln in buf):
        raise ValueError("Oracle script has a trailing statement without a '/' terminator")
    return statements


def _is_comment_or_blank(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("--")


def _to_python(value: Any) -> Any:
    """Convert pandas/numpy scalars and NaN/NaT to plain Python for DB drivers."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return value


class DuckDb(Database):
    backend = "duckdb"

    def __init__(self, path: Path) -> None:
        import duckdb

        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.con = duckdb.connect(str(path))

    def execute(self, sql: str, params: Params = None) -> None:
        self.con.execute(sql, params)

    def query_df(self, sql: str, params: Params = None) -> pd.DataFrame:
        return self.con.execute(sql, params).df()

    def run_script(self, path: Path) -> int:
        text = path.read_text(encoding="utf-8")
        statements = [
            s for s in text.split(";") if not all(_is_comment_or_blank(ln) for ln in s.splitlines())
        ]
        self.con.execute(text)
        return len(statements)

    def insert_df(self, table: str, df: pd.DataFrame) -> int:
        self.con.register("_insert_df", df)
        try:
            self.con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM _insert_df")
        finally:
            self.con.unregister("_insert_df")
        return len(df)

    def close(self) -> None:
        self.con.close()


class OracleDb(Database):
    backend = "oracle"
    batch_size = 50_000

    def __init__(self, settings: Settings) -> None:
        import oracledb

        cfg = settings.db.oracle
        if not cfg.password:
            raise ServiceUnavailableError(
                "Oracle password not set: add ORACLE_APP_PASSWORD to .env"
            )
        try:
            self.con = oracledb.connect(
                user=cfg.user, password=cfg.password, dsn=cfg.dsn, tcp_connect_timeout=5
            )
        except oracledb.Error as exc:
            raise ServiceUnavailableError(f"Oracle not reachable at {cfg.dsn}: {exc}") from exc

    def execute(self, sql: str, params: Params = None) -> None:
        with self.con.cursor() as cur:
            cur.execute(sql, params or {})
        self.con.commit()

    def query_df(self, sql: str, params: Params = None) -> pd.DataFrame:
        with self.con.cursor() as cur:
            cur.execute(sql, params or {})
            cols = [d[0].lower() for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)

    def run_script(self, path: Path) -> int:
        statements = split_oracle_script(path.read_text(encoding="utf-8"))
        with self.con.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        self.con.commit()
        return len(statements)

    def insert_df(self, table: str, df: pd.DataFrame) -> int:
        cols = list(df.columns)
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) "
            f"VALUES ({', '.join(f':{i + 1}' for i in range(len(cols)))})"
        )
        rows = [tuple(_to_python(v) for v in row) for row in df.itertuples(index=False)]
        with self.con.cursor() as cur:
            for start in range(0, len(rows), self.batch_size):
                cur.executemany(sql, rows[start : start + self.batch_size])
        self.con.commit()
        return len(rows)

    def close(self) -> None:
        self.con.close()


def get_db(settings: Settings | None = None, backend: str | None = None) -> Database:
    """Open the configured backend; fall back to DuckDB if Oracle is down and allowed."""
    settings = settings or get_settings()
    backend = backend or settings.db.backend
    if backend == "oracle":
        try:
            return OracleDb(settings)
        except ServiceUnavailableError as exc:
            if not settings.db.fallback_to_duckdb:
                raise
            log.warning("%s -> falling back to DuckDB", exc)
    return DuckDb(settings.path(settings.db.duckdb_path))
