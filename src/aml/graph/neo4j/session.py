"""One shared Neo4j driver per process, and the check that the graph still matches its source."""

from __future__ import annotations

import atexit
from datetime import datetime

import neo4j

from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.neo4j import client
from aml.graph.neo4j.guard import GraphError
from aml.graph.neo4j.sync import graph_counts, read_state, source_stats

_DRIVERS: dict[tuple[str, str, str], neo4j.Driver] = {}


class StaleGraphError(GraphError):
    """The graph was never synced, or no longer matches the database it was synced from."""


def _close_all() -> None:
    for driver in _DRIVERS.values():
        driver.close()
    _DRIVERS.clear()


atexit.register(_close_all)


def shared_driver(settings: Settings) -> neo4j.Driver:
    """One driver per (uri, user, database); a failed connection is not cached."""
    cfg = settings.neo4j
    key = (cfg.uri, cfg.user, cfg.database)
    driver = _DRIVERS.get(key)
    if driver is None:
        driver = client.open_driver(settings)  # raises ServiceUnavailableError
        _DRIVERS[key] = driver
    return driver


def check_fresh(
    state: tuple[datetime | None, str] | None,
    backend: str,
    graph_transfers: int,
    source_transfers: int,
) -> None:
    """Raise `StaleGraphError` unless the graph came from ``backend`` and has every transfer."""
    if state is None:
        raise StaleGraphError("graph not synced: run aml graph sync")
    if state[1] != backend:
        raise StaleGraphError(
            f"graph was synced from {state[1]} but the database is {backend}: "
            "run aml graph sync --full"
        )
    if graph_transfers != source_transfers:
        raise StaleGraphError(
            f"graph is out of sync ({graph_transfers} of {source_transfers} transfers): "
            "run aml graph sync"
        )


def require_fresh(driver: neo4j.Driver, db: Database, settings: Settings) -> None:
    """Compare the graph with ``db`` (never syncs); raises `StaleGraphError`."""
    state = read_state(driver, settings)
    graph_transfers = graph_counts(driver, settings)["TRANSFERRED_TO"]
    check_fresh(state, db.backend, graph_transfers, source_stats(db).transfers)
