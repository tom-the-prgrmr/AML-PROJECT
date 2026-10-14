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
        "ddl/060_dq.sql",
        "ddl/070_audit_log_partitioning.sql",  # before 050, which recompiles the triggers
        "ddl/080_screening.sql",
        "ddl/090_screening_state.sql",
        "ddl/100_entity_resolution.sql",
        "ddl/110_monitoring.sql",
        "ddl/120_property_graph.sql",
        "ddl/130_network.sql",
        "ddl/140_graph_sync.sql",
        "ddl/150_gds.sql",
        "ddl/160_cases.sql",
        "ddl/170_case_suppression.sql",
        "ddl/180_case_prioritization.sql",
        "ddl/190_memo_analysis.sql",
        "ddl/200_ml_anomaly.sql",
        "ddl/210_screening_ml.sql",
        "ddl/050_security_objects.sql",  # security objects are applied last
    ),
    "duckdb": (
        "ddl/000_audit_log.sql",
        "ddl/010_datagen.sql",
        "ddl/040_acct_edge_daily.sql",
        "ddl/060_dq.sql",
        "ddl/080_screening.sql",
        "ddl/090_screening_state.sql",
        "ddl/100_entity_resolution.sql",
        "ddl/110_monitoring.sql",
        "ddl/130_network.sql",
        "ddl/140_graph_sync.sql",
        "ddl/150_gds.sql",
        "ddl/160_cases.sql",
        "ddl/170_case_suppression.sql",
        "ddl/180_case_prioritization.sql",
        "ddl/190_memo_analysis.sql",
        "ddl/200_ml_anomaly.sql",
        "ddl/210_screening_ml.sql",
        "ddl/050_customers_masked.sql",  # security objects are applied last, after all tables exist
    ),
}


AUDIT_PARTITION_SCRIPT = "ddl/070_audit_log_partitioning.sql"

# script -> (table, reason) for scripts that convert a heap table to interval partitioning
CONVERSIONS: dict[str, tuple[str, str]] = {
    PARTITION_SCRIPT: (
        "transactions",
        "Converted heap table transactions to monthly interval partitioning on "
        "txn_ts (online); txn_ts indexes are local, the primary key stays global.",
    ),
    AUDIT_PARTITION_SCRIPT: (
        "audit_log",
        "Converted heap table audit_log to monthly interval partitioning on event_ts "
        "(ALTER TABLE ... MODIFY PARTITION BY ... ONLINE UPDATE INDEXES); "
        "the primary key stays global and the append-only triggers are kept.",
    ),
}


def _is_partitioned(db: Database, table: str) -> bool:
    df = db.query_df(
        f"SELECT COUNT(*) AS n FROM user_part_tables WHERE table_name = '{table.upper()}'"
    )
    return int(df.iloc[0, 0]) > 0


def apply_schema(db: Database) -> dict[str, int]:
    """Run every schema script for ``db``; return ``script -> number of statements``.

    Audits ``PARTITIONED`` only when this call actually converted the table.
    """
    counts: dict[str, int] = {}
    for script in SCHEMA_SCRIPTS[db.backend]:
        conversion = CONVERSIONS.get(script) if db.backend == "oracle" else None
        was_partitioned = _is_partitioned(db, conversion[0]) if conversion else True
        counts[script] = db.run_named_script(script)
        if conversion and not was_partitioned and _is_partitioned(db, conversion[0]):
            audit(
                db,
                module="dba",
                entity_type="table",
                entity_id=conversion[0],
                decision="PARTITIONED",
                reason=conversion[1],
                version=script,
            )
    return counts
