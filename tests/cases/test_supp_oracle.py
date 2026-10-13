"""AC9 for specs/case-suppression.md: Oracle and DuckDB suppress the same item on TINY.

The Oracle schema is shared and keeps earlier runs, dispositions and good-guy rows, so nothing
history-dependent is asserted as a constant. The test also removes the disposition and good-guy
rows it wrote: a leftover FALSE_POSITIVE on the TINY case would change the numbers of
`test_oracle_parity.py` on the next run (audit rows stay: audit_log cannot be purged).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import Database, DuckDb, OracleDb

from .helpers import AS_OF, mod, query, run_cases
from .supp_helpers import GG_CASE, day, dispose, item_set


def _build(db: Database, settings: Settings, parquet: Path) -> None:
    mod("aml.datagen.load").load_parquet(db, parquet)
    mod("aml.entity_resolution.runner").run_er(db, settings, as_of=AS_OF)
    mod("aml.screening.runner").run_screening(db, settings, as_of=AS_OF)
    mod("aml.monitoring.runner").run_monitoring(db, settings, as_of=AS_OF)
    mod("aml.graph.network.runner").run_network(db, settings, as_of=AS_OF)
    mod("aml.dq.runner").run_dq(db, settings, as_of=AS_OF)
    run_cases(db, settings, as_of=AS_OF)  # the first run of a fresh backend


def _run_and_read(db: Database, settings: Settings) -> tuple[Any, dict[str, Any]]:
    """A run after the clearance; return it and the good-guy row of the pair."""
    run = run_cases(db, settings, as_of=AS_OF)
    row = query(
        db,
        "SELECT cleared_on, expires_on, customer_fingerprint, entry_fingerprint "
        "FROM good_guy_current WHERE cif = 'CIF00000041' AND entry_id = 'WL000199'",
    ).iloc[0]
    fields = {
        "cleared_on": day(row["cleared_on"]),
        "expires_on": day(row["expires_on"]),
        "customer_fingerprint": row["customer_fingerprint"],
        "entry_fingerprint": row["entry_fingerprint"],
    }
    return run, fields


def _forget(db: Database, disposition_id: int) -> None:
    """Remove what this test wrote (best effort; the tables hold nothing the audit relies on)."""
    for table in ("good_guy_list", "case_dispositions"):
        try:
            db.execute(f"DELETE FROM {table} WHERE disposition_id = {disposition_id}")
        except Exception:
            continue


@pytest.mark.oracle
def test_ac9_oracle_and_duckdb_agree_on_the_good_guy(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    schema = mod("aml.dba.schema")
    # pinned: GDS rows left on the shared Oracle would make `auto` pick gds
    pinned = {"AML__CASES__GRAPH_FEATURES": "networkx"}
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle"), **pinned})
    with OracleDb(osettings) as odb:
        schema.apply_schema(odb)
        _build(odb, osettings, tiny_parquet)
        disposition_id = dispose(odb, osettings, GG_CASE, reason="test clearance")
        try:
            orun, ogood = _run_and_read(odb, osettings)
            oitems = item_set(odb)
            tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
            views = set(odb.query_df("SELECT view_name FROM user_views").iloc[:, 0])
            schema.apply_schema(odb)  # idempotent on a second call
        finally:
            _forget(odb, disposition_id)

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb", **pinned})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        _build(ddb, dsettings, tiny_parquet)
        dispose(ddb, dsettings, GG_CASE, reason="test clearance")
        drun, dgood = _run_and_read(ddb, dsettings)
        ditems = item_set(ddb)

    for run in (orun, drun):
        assert (run.suppressed, run.active, run.cases) == (1, 73, 51)
    assert ogood == dgood
    assert oitems == ditems
    assert "GOOD_GUY_LIST" in tables
    assert "GOOD_GUY_CURRENT" in views
