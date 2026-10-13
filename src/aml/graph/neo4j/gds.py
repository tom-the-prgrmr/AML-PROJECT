"""Graph Data Science on the Neo4j projection, written back to the system of record as features.

Three in-memory graphs are projected inside READ sessions, read with ``.stream`` only and dropped
again in a ``finally``; nothing is written to Neo4j. The streams become one feature row per account
(`features.build_features`), stored in ``gds_account_features``. Every failure happens before the
first write, so an error leaves no rows and no in-memory graph. Only features are produced: no
alert, no score.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import neo4j
import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.neo4j.client import run_read_file
from aml.graph.neo4j.features import GdsStreams, build_features
from aml.graph.neo4j.gds_record import next_run_id, write_run
from aml.graph.neo4j.guard import GraphError
from aml.graph.neo4j.session import StaleGraphError, require_fresh, shared_driver
from aml.graph.neo4j.sync import _ts

GRAPH_NAMES = ("accounts", "accounts_undirected", "shared")
_PROJECTIONS = {
    "accounts": "gds/project_accounts.cypher",
    "accounts_undirected": "gds/project_accounts_undirected.cypher",
    "shared": "gds/project_shared.cypher",
}
Sizes = dict[str, tuple[int, int]]


class GdsError(GraphError):
    """GDS is missing, the graph is stale, or a GDS call failed (nothing was written)."""


@dataclass(frozen=True)
class GdsRun:
    run_id: int
    as_of: date
    accounts: int  # gds_account_features rows of the run
    active_accounts: int  # nodes of the account graph
    wcc_components: int
    louvain_communities: int
    shared_clusters: int
    graphs: Sizes  # name -> (nodes, relationships)
    sync_run_id: int
    watermark: datetime | None
    gds_version: str
    seconds: float


def _read(
    driver: neo4j.Driver, settings: Settings, name: str, params: dict[str, Any] | None = None
) -> pd.DataFrame:
    return run_read_file(driver, settings, name, params, procedures=settings.gds.procedures)


def _names(settings: Settings) -> dict[str, str]:
    return {key: f"{settings.gds.graph_prefix}_{key}" for key in GRAPH_NAMES}


def _drop_all(driver: neo4j.Driver, settings: Settings, names: dict[str, str]) -> None:
    """Drop every in-memory graph; one failing drop does not stop the others."""
    failure: Exception | None = None
    for graph in names.values():
        try:
            _read(driver, settings, "gds/drop.cypher", {"graph": graph})
        except Exception as exc:
            failure = failure or exc
    if failure is not None:
        raise failure


def _project(driver: neo4j.Driver, settings: Settings, names: dict[str, str], as_of: date) -> Sizes:
    cutoff = as_of + timedelta(days=1)
    since = cutoff - timedelta(days=settings.network.hubs.lookback_days)
    cap = settings.network.shared_attributes.max_customers_per_value
    sizes: Sizes = {}
    for key, file in _PROJECTIONS.items():
        params: dict[str, Any] = {"graph": names[key]}
        if key == "shared":
            params["max_customers_per_value"] = cap
        else:
            params |= {"since": since, "cutoff": cutoff}
        frame = _read(driver, settings, file, params)
        # no pair matched: no row, or a row of nulls; the graph does not exist in memory
        empty = frame.empty or bool(pd.isna(frame["nodes"].iloc[0]))
        sizes[key] = (
            (0, 0) if empty else (int(frame["nodes"].iloc[0]), int(frame["relationships"].iloc[0]))
        )
    return sizes


def _stream(
    driver: neo4j.Driver,
    settings: Settings,
    graph: str,
    size: tuple[int, int],
    file: str,
    columns: tuple[str, str],
    **params: Any,
) -> pd.DataFrame:
    if size == (0, 0):
        return pd.DataFrame({c: [] for c in columns})
    args = {"graph": graph, "concurrency": settings.gds.concurrency, **params}
    return _read(driver, settings, file, args)[list(columns)]


def _streams(
    driver: neo4j.Driver, settings: Settings, names: dict[str, str], sizes: Sizes
) -> GdsStreams:
    cfg = settings.gds
    acc, und, shr = names["accounts"], names["accounts_undirected"], names["shared"]
    n_acc, n_und, n_shr = sizes["accounts"], sizes["accounts_undirected"], sizes["shared"]
    pair = ("account_id", "score")

    def degree(orientation: str, weight: str | None) -> pd.DataFrame:
        return _stream(
            driver, settings, acc, n_acc, "gds/degree.cypher", pair,
            orientation=orientation, weight=weight,
        )  # fmt: skip

    return GdsStreams(
        in_degree=degree("REVERSE", None),
        out_degree=degree("NATURAL", None),
        in_vnd=degree("REVERSE", "total_vnd"),
        out_vnd=degree("NATURAL", "total_vnd"),
        pagerank=_stream(
            driver, settings, acc, n_acc, "gds/pagerank.cypher", pair,
            damping=settings.network.hubs.pagerank_alpha,
            max_iterations=cfg.pagerank_max_iterations,
            tolerance=cfg.pagerank_tolerance,
        ),
        wcc=_stream(
            driver, settings, und, n_und, "gds/wcc_accounts.cypher", ("account_id", "component")
        ),
        louvain=_stream(
            driver, settings, und, n_und, "gds/louvain_accounts.cypher",
            ("account_id", "community"),
            max_levels=cfg.louvain_max_levels,
            max_iterations=cfg.louvain_max_iterations,
            tolerance=cfg.louvain_tolerance,
        ),
        shared=_stream(
            driver, settings, shr, n_shr, "gds/wcc_shared.cypher",
            ("golden_customer_id", "component"),
        ),
    )  # fmt: skip


def _compute(driver: neo4j.Driver, settings: Settings, as_of: date) -> tuple[GdsStreams, Sizes]:
    """Project, stream and always drop the in-memory graphs."""
    names = _names(settings)
    try:
        _drop_all(driver, settings, names)
        sizes = _project(driver, settings, names, as_of)
        streams = _streams(driver, settings, names, sizes)
    except BaseException:
        with contextlib.suppress(Exception):  # the first failure is the one to report
            _drop_all(driver, settings, names)
        raise
    _drop_all(driver, settings, names)
    return streams, sizes


def _sync_state(driver: neo4j.Driver, settings: Settings) -> tuple[int, datetime | None]:
    """(id of the last sync run, transaction watermark) of the projection."""
    row = run_read_file(driver, settings, "read/sync_state.cypher").iloc[0]
    last = row["last_run_id"]
    return (0 if last is None or bool(pd.isna(last)) else int(last)), _ts(row["txn_watermark"])


def _owners(db: Database) -> tuple[pd.DataFrame, dict[str, str]]:
    """The accounts and the golden customer of every CIF (``G-<cif>`` when ER did not see it)."""
    accounts = db.query_df("SELECT account_id, cif FROM accounts")
    cifs = db.query_df("SELECT cif FROM customers")["cif"]
    golden = db.query_df("SELECT cif, golden_customer_id FROM customer_golden")
    known = dict(zip(golden["cif"], golden["golden_customer_id"], strict=True))
    owner_of_cif = {str(c): str(known.get(c, f"G-{c}")) for c in (*cifs, *accounts["cif"])}
    return accounts, owner_of_cif


def run_gds(
    db: Database, settings: Settings, *, as_of: date | None = None, actor: str | None = None
) -> GdsRun:
    """Compute the GDS features as of ``as_of`` (default: reference date) and store them."""
    started = time.perf_counter()
    as_of = as_of or settings.data.reference_date
    driver = shared_driver(settings)  # ServiceUnavailableError is the caller's to handle
    try:
        try:
            require_fresh(driver, db, settings)
        except StaleGraphError as exc:
            raise GdsError(str(exc)) from exc
        try:
            version = str(_read(driver, settings, "gds/version.cypher")["version"].iloc[0])
        except GraphError as exc:
            raise GdsError(f"GDS plugin not available on the Neo4j server: {exc}") from exc
        sync_run_id, watermark = _sync_state(driver, settings)
        streams, sizes = _compute(driver, settings, as_of)
    except GdsError:
        raise
    except GraphError as exc:
        raise GdsError(f"GDS failed: {exc}") from exc

    accounts, owner_of_cif = _owners(db)
    features = build_features(accounts, owner_of_cif, streams)
    run = GdsRun(
        run_id=next_run_id(db),
        as_of=as_of,
        accounts=len(features),
        active_accounts=sizes["accounts"][0],
        wcc_components=int(streams.wcc["component"].nunique()),
        louvain_communities=int(streams.louvain["community"].nunique()),
        shared_clusters=int(features["shared_cluster_id"].nunique()),
        graphs=sizes,
        sync_run_id=sync_run_id,
        watermark=watermark,
        gds_version=version,
        seconds=round(time.perf_counter() - started, 3),
    )
    write_run(db, settings, run, features, source_backend=db.backend, actor=actor)
    return run
