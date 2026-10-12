"""Helpers for the Phase 6b-i tests (specs/neo4j-queries.md): MINI-T, synced fixtures, CLI."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from typer.testing import CliRunner

from aml.common.config import Settings, get_settings
from aml.common.db import Database, DuckDb
from aml.dba.edges import refresh_acct_edge_daily
from tests.graph.helpers import load_mini
from tests.neo4j_sync.helpers import (
    OFFLINE_URI,
    TINY_S11,
    client,
    graph_audit,
    mod,
    neo_settings,
    none_if_nan,
    run_sync,
    s11,
)
from tests.network.helpers import add_accounts, add_customers, add_golden

__all__ = [
    "MINI_T_S11",
    "OFFLINE_URI",
    "TINY_S11",
    "Synced",
    "cells",
    "cli",
    "graph_audit",
    "load_mini_t",
    "mod",
    "neo_settings",
    "query",
    "rows",
    "set_env",
    "synced_db",
    "trace",
    "tuples",
]

MINI_T_S11 = s11(1, 10, 0, 0, 0, 1, 0, 0, 0, 12, 12)


def load_mini_t(db: Database) -> None:
    """MINI-T of the spec: the 14 MINI transactions, customer C-A owning account A, golden."""
    load_mini(db)
    add_customers(db, [("C-A", None, None, None, None, None, None)])
    add_accounts(db, [("A", "C-A", "CURRENT")])
    add_golden(db, [("C-A", "G-C-A")])
    refresh_acct_edge_daily(db)


@dataclass
class Synced:
    """A DuckDB loaded with a data set, synced into Neo4j (`run_sync(full=True)`)."""

    db: DuckDb
    settings: Settings
    driver: Any
    run: Any


@contextmanager
def synced_db(
    path: Path,
    load: Callable[[DuckDb], None] | None = None,
    *,
    template: Path | None = None,
    expect_graph: dict[str, int] | None = None,
    settings: Settings | None = None,
) -> Iterator[Synced]:
    """Load into a fresh DuckDB at ``path``, wipe Neo4j, sync once (module-scoped use)."""
    settings = settings or neo_settings()
    if template is not None:
        shutil.copy(template, path)
    db = DuckDb(path)
    driver = client().open_driver(settings)
    try:
        if load is not None:
            load(db)
        client().run_write_file(driver, settings, "sync/wipe.cypher")
        run = run_sync(db, settings, full=True)
        assert run.in_sync is True
        if expect_graph is not None:
            assert run.graph == expect_graph
        yield Synced(db, settings, driver, run)
    finally:
        driver.close()
        db.close()


def trace(db: Database, settings: Settings, account: str, **kw: Any) -> Any:
    return mod("aml.graph.trace").trace(db, settings, account, **kw)


def query(db: Database, settings: Settings, name: str, **kw: Any) -> Any:
    return mod("aml.graph.neo4j.queries").run_query(db, settings, name, **kw)


def _plain(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return list(value)
    if hasattr(value, "tolist") and not isinstance(value, str):
        return value.tolist()
    return none_if_nan(value)


def tuples(frame: pd.DataFrame, columns: list[str]) -> list[tuple[Any, ...]]:
    """The given columns of ``frame`` as plain Python tuples (lists stay lists)."""
    return [tuple(_plain(v) for v in r) for r in frame[columns].itertuples(index=False)]


def rows(result: Any, columns: list[str]) -> list[tuple[Any, ...]]:
    return tuples(result.rows, columns)


def cells(frame: pd.DataFrame) -> list[str]:
    return [str(_plain(v)) for r in frame.itertuples(index=False) for v in r]


def cli(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, list(args))


def set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
