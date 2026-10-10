"""Optimizer statistics for the dataset tables (Oracle only)."""

from __future__ import annotations

from aml.common.audit import audit
from aml.common.db import Database
from aml.datagen.pipeline import TABLES

STATS_TABLES = [*TABLES, "acct_edge_daily"]


def gather_stats(db: Database) -> list[str]:
    """Gather statistics (incremental on ``transactions``); return the tables processed.

    DuckDB maintains its own statistics, so it returns ``[]`` and writes no audit row.
    """
    if db.backend != "oracle":
        return []
    db.execute(
        "BEGIN DBMS_STATS.SET_TABLE_PREFS(USER, 'TRANSACTIONS', 'INCREMENTAL', 'TRUE'); END;"
    )
    for table in STATS_TABLES:
        db.execute(f"BEGIN DBMS_STATS.GATHER_TABLE_STATS(USER, '{table.upper()}'); END;")
    audit(
        db,
        module="dba",
        entity_type="table",
        entity_id="dataset",
        decision="STATS_GATHERED",
        reason=(
            f"Gathered optimizer statistics on {len(STATS_TABLES)} tables; "
            "incremental partition statistics enabled on transactions."
        ),
        details={"tables": STATS_TABLES},
    )
    return list(STATS_TABLES)
