"""Apply the full schema for the active backend (idempotent)."""

from __future__ import annotations

from aml.common.audit import audit
from aml.common.db import Database

PARTITION_SCRIPT = "ddl/020_transactions_partitioning.sql"

SCHEMA_SCRIPTS: dict[str, tuple[str, ...]] = {
    "oracle": (
        "ddl/000_audit_log.sql",
        "ddl/010_datagen.sql",
        "ddl/020_transactions_partitioning.sql",
        "ddl/030_constraints_indexes.sql",
        "ddl/040_acct_edge_daily.sql",
        "ddl/060_dq.sql",  # security objects are applied last, after all tables exist
        "ddl/050_security_objects.sql",
    ),
    "duckdb": (
        "ddl/000_audit_log.sql",
        "ddl/010_datagen.sql",
        "ddl/040_acct_edge_daily.sql",
        "ddl/060_dq.sql",  # security objects are applied last, after all tables exist
        "ddl/050_customers_masked.sql",
    ),
}


def _is_partitioned(db: Database) -> bool:
    df = db.query_df("SELECT COUNT(*) AS n FROM user_part_tables WHERE table_name = 'TRANSACTIONS'")
    return int(df.iloc[0, 0]) > 0


def apply_schema(db: Database) -> dict[str, int]:
    """Run every schema script for ``db``; return ``script -> number of statements``.

    Audits ``PARTITIONED`` only when this call actually converted ``transactions``.
    """
    counts: dict[str, int] = {}
    for script in SCHEMA_SCRIPTS[db.backend]:
        was_partitioned = _is_partitioned(db) if script == PARTITION_SCRIPT else True
        counts[script] = db.run_named_script(script)
        if script == PARTITION_SCRIPT and not was_partitioned and _is_partitioned(db):
            audit(
                db,
                module="dba",
                entity_type="table",
                entity_id="transactions",
                decision="PARTITIONED",
                reason=(
                    "Converted heap table transactions to monthly interval partitioning on "
                    "txn_ts (online); txn_ts indexes are local, the primary key stays global."
                ),
                version=script,
            )
    return counts
