"""Refresh the ``acct_edge_daily`` aggregate (Oracle materialized view / DuckDB table)."""

from __future__ import annotations

from aml.common.audit import audit
from aml.common.db import Database

DUCKDB_SCRIPT = "ddl/040_acct_edge_daily.sql"


def refresh_acct_edge_daily(db: Database) -> int:
    """Rebuild ``acct_edge_daily`` from ``transactions``; audit and return its row count."""
    if db.backend == "oracle":
        db.execute(
            "BEGIN DBMS_MVIEW.REFRESH('ACCT_EDGE_DAILY', 'C', atomic_refresh => FALSE); END;"
        )
        method = "complete (non-atomic) materialized view refresh"
    else:
        db.run_named_script(DUCKDB_SCRIPT)
        method = "CREATE OR REPLACE TABLE rebuild"
    rows = int(db.query_df("SELECT COUNT(*) AS n FROM acct_edge_daily").iloc[0, 0])
    audit(
        db,
        module="dba",
        entity_type="table",
        entity_id="acct_edge_daily",
        decision="REFRESHED",
        reason=f"Rebuilt per-day account edges from transactions via {method}: {rows} rows.",
        version=DUCKDB_SCRIPT,
        details={"rows": rows},
    )
    return rows
