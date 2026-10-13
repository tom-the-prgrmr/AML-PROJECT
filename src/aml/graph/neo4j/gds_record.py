"""Run log, feature rows and audit trail of a GDS run (kept apart from the Neo4j work in `gds.py`).

Everything here goes through ``db``: one `gds_runs` row, the feature rows in one bulk insert, then
one audit row. Append-only, nothing is updated or deleted. The three writes are not one
transaction: if a later one fails, the run id is still used up (`next_run_id` looks at both
tables), so the next run is not blocked by the half-written one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database

if TYPE_CHECKING:
    from aml.graph.neo4j.gds import GdsRun

AUDIT_VERSION = "gds/v1"


def next_run_id(db: Database) -> int:
    """One past the highest run id in either table, so a half-written run is never reused."""
    highest = 0
    for table in ("gds_runs", "gds_account_features"):
        frame = db.query_df(f"SELECT COALESCE(MAX(run_id), 0) AS n FROM {table}")
        highest = max(highest, int(frame.iloc[0, 0]))
    return highest + 1


def _statement(db: Database, name: str) -> str:
    """The single statement of a `.sql` file, without the Oracle `/` or a trailing `;`."""
    lines = db.sql_file(name).read_text(encoding="utf-8").strip().splitlines()
    if lines and lines[-1].strip() == "/":
        lines = lines[:-1]
    return "\n".join(lines).strip().rstrip(";")


def run_params(settings: Settings, graphs: dict[str, tuple[int, int]]) -> dict[str, Any]:
    hubs = settings.network.hubs
    gds = settings.gds
    return {
        "lookback_days": hubs.lookback_days,
        "max_customers_per_value": settings.network.shared_attributes.max_customers_per_value,
        "pagerank_alpha": hubs.pagerank_alpha,
        "pagerank_max_iterations": gds.pagerank_max_iterations,
        "pagerank_tolerance": gds.pagerank_tolerance,
        "louvain_max_levels": gds.louvain_max_levels,
        "louvain_max_iterations": gds.louvain_max_iterations,
        "louvain_tolerance": gds.louvain_tolerance,
        "concurrency": gds.concurrency,
        "graphs": {name: list(counts) for name, counts in graphs.items()},
    }


def gds_reason(run: GdsRun) -> str:
    return (
        f"GDS {run.gds_version} on the Neo4j projection (sync run {run.sync_run_id}): "
        f"wrote features for {run.accounts} accounts, {run.active_accounts} with transfers; "
        f"{run.wcc_components} components, {run.louvain_communities} communities, "
        f"{run.shared_clusters} shared-attribute clusters"
    )


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat(timespec="seconds")


def write_run(
    db: Database,
    settings: Settings,
    run: GdsRun,
    features: pd.DataFrame,
    *,
    source_backend: str,
    actor: str | None,
) -> None:
    """Insert the `gds_runs` row, the features and the audit row (in that order)."""
    db.execute(
        _statement(db, "graph/insert_gds_run.sql"),
        [
            run.run_id,
            datetime.now(UTC).replace(tzinfo=None),
            run.as_of,
            source_backend,
            run.sync_run_id,
            run.watermark,
            run.gds_version,
            run.accounts,
            run.active_accounts,
            run.wcc_components,
            run.louvain_communities,
            run.shared_clusters,
            run.seconds,
            json.dumps(run_params(settings, run.graphs)),
        ],
    )
    rows = features.copy()
    rows.insert(0, "run_id", run.run_id)
    db.insert_df("gds_account_features", rows)
    audit(
        db,
        module="graph",
        entity_type="gds_run",
        entity_id=str(run.run_id),
        decision="GDS_FEATURES_WRITTEN",
        reason=gds_reason(run),
        version=AUDIT_VERSION,
        details={
            "run_id": run.run_id,
            "as_of": run.as_of.isoformat(),
            "sync_run_id": run.sync_run_id,
            "watermark": _iso(run.watermark),
            "gds_version": run.gds_version,
            "accounts": run.accounts,
            "active_accounts": run.active_accounts,
            "wcc_components": run.wcc_components,
            "louvain_communities": run.louvain_communities,
            "shared_clusters": run.shared_clusters,
            "graphs": {name: list(counts) for name, counts in run.graphs.items()},
        },
        **({"actor": actor} if actor else {}),
    )
