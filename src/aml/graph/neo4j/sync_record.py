"""Run log and audit trail of a projection sync (kept apart from the Neo4j work in `sync.py`).

Both are written through the application's own connection (``db``), never through the read-only
source connection. Oracle's reserved word ``MODE`` is handled in the per-backend INSERT file.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from aml.common.audit import audit
from aml.common.db import Database
from aml.graph.neo4j.extract import NODE_LABELS, REL_TYPES

if TYPE_CHECKING:
    from aml.graph.neo4j.sync import SyncRun

AUDIT_VERSION = "graph_sync/v1"
OUT_OF_SYNC = "OUT OF SYNC: run aml graph sync --full"


def next_run_id(db: Database) -> int:
    frame = db.query_df("SELECT COALESCE(MAX(run_id), 0) + 1 AS n FROM graph_sync_runs")
    return int(frame.iloc[0, 0])


def _statement(db: Database, name: str) -> str:
    """The single statement of a `.sql` file, without the Oracle `/` or a trailing `;`."""
    lines = db.sql_file(name).read_text(encoding="utf-8").strip().splitlines()
    if lines and lines[-1].strip() == "/":
        lines = lines[:-1]
    return "\n".join(lines).strip().rstrip(";")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat(timespec="seconds")


def _totals(run: SyncRun) -> tuple[int, int]:
    return sum(run.sent[k] for k in NODE_LABELS), sum(run.sent[k] for k in REL_TYPES)


def sync_reason(run: SyncRun) -> str:
    nodes, rels = _totals(run)
    watermark = run.watermark_to if run.watermark_to is not None else "-"
    reason = (
        f"{run.mode} sync from {run.source_backend}: sent {nodes} nodes and {rels} relationships, "
        f"pruned {run.pruned}, swept {run.swept}; "
        f"graph has {run.graph['TRANSFERRED_TO']} of {run.source['TRANSFERRED_TO']} transfers and "
        f"{run.graph['SENT_TO']} of {run.source['SENT_TO']} daily edges; watermark {watermark}"
    )
    return reason if run.in_sync else f"{reason}; {OUT_OF_SYNC}"


def record_run(db: Database, run: SyncRun) -> None:
    """Insert one `graph_sync_runs` row."""
    nodes, rels = _totals(run)
    details = json.dumps({"sent": run.sent, "graph": run.graph, "source": run.source})
    db.execute(
        _statement(db, "graph/insert_sync_run.sql"),
        [
            run.run_id,
            datetime.now(UTC).replace(tzinfo=None),
            run.mode,
            run.source_backend,
            run.source_user,
            run.since,
            run.watermark_from,
            run.watermark_to,
            run.er_run_id,
            nodes,
            rels,
            run.pruned,
            run.swept,
            run.lag_before_seconds,
            run.lag_after_seconds,
            run.seconds,
            int(run.in_sync),
            details,
        ],
    )


def _actor(actor: str | None) -> dict[str, Any]:
    return {"actor": actor} if actor else {}


def audit_synced(db: Database, run: SyncRun, actor: str | None) -> None:
    audit(
        db,
        module="graph",
        entity_type="neo4j",
        entity_id="projection",
        decision="SYNCED",
        reason=sync_reason(run),
        version=AUDIT_VERSION,
        details={
            "run_id": run.run_id,
            "mode": run.mode,
            "source_backend": run.source_backend,
            "source_user": run.source_user,
            "since": _iso(run.since),
            "watermark_to": _iso(run.watermark_to),
            "sent": run.sent,
            "graph": run.graph,
            "source": run.source,
            "pruned": run.pruned,
            "swept": run.swept,
            "lag_before_seconds": run.lag_before_seconds,
            "lag_after_seconds": run.lag_after_seconds,
            "in_sync": run.in_sync,
        },
        **_actor(actor),
    )


def audit_failed(db: Database, run_id: int, mode: str, error: Exception, actor: str | None) -> None:
    audit(
        db,
        module="graph",
        entity_type="neo4j",
        entity_id="projection",
        decision="SYNC_FAILED",
        reason=f"{mode} sync failed: {error}",
        version=AUDIT_VERSION,
        details={"run_id": run_id, "mode": mode, "error": str(error)},
        **_actor(actor),
    )
