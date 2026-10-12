"""AC10 for specs/neo4j-sync.md: the Oracle source (read-only user) gives the same graph as DuckDB.

Needs Oracle, Neo4j, ORACLE_SYS_PASSWORD and ORACLE_DEMO_PASSWORD. Like the 2b security tests it
reloads TINY into the schema owner and re-applies the grants; it leaves rows in `graph_sync_runs`
and `audit_log`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import DuckDb, OracleDb
from tests.security.helpers import admin_db, demo_db

from .conftest import Neo
from .helpers import (
    GRAPH_SYNC_GRANTS,
    TINY_S11,
    graph_snapshot,
    mod,
    neo_settings,
    run_sync,
    s11,
    scalar,
)

pytestmark = [pytest.mark.oracle, pytest.mark.neo4j]


@pytest.fixture
def oracle_settings() -> Settings:
    env = {**read_environ(), "DB_BACKEND": "oracle"}
    for name in ("ORACLE_SYS_PASSWORD", "ORACLE_DEMO_PASSWORD"):
        if not env.get(name):
            pytest.skip(f"{name} is not set in .env")
    return load_settings(environ=env)


def _fails(db: OracleDb, sql: str, code: str) -> None:
    with pytest.raises(Exception, match=code):
        db.query_df(sql) if sql.lstrip().upper().startswith("SELECT") else db.execute(sql)


def test_ac10_oracle_source_matches_duckdb_source(
    neo: Neo, oracle_settings: Settings, tiny_parquet: Path, tmp_path: Path
) -> None:
    load = mod("aml.datagen.load")
    er = mod("aml.entity_resolution.runner")
    extract = mod("aml.graph.neo4j.extract")
    owner = oracle_settings.db.oracle.user
    dsettings = neo_settings()
    d, s = neo.driver, neo.settings

    with OracleDb(oracle_settings) as odb:
        load.load_parquet(odb, tiny_parquet)
        er.run_er(odb, oracle_settings)
    mod("aml.dba.security").apply_security(oracle_settings)

    with DuckDb(tmp_path / "tiny.duckdb") as ddb:
        load.load_parquet(ddb, tiny_parquet)
        er.run_er(ddb, dsettings)
        duck_run = run_sync(ddb, dsettings, full=True)
    assert duck_run.in_sync is True
    from_duck = graph_snapshot(d, s)
    assert [len(v) for v in from_duck.values()] == [273, 1314, 1357, 3651, 3575]

    with OracleDb(oracle_settings) as odb:
        before = int(scalar(odb, "SELECT COUNT(*) FROM graph_sync_runs"))
        with pytest.raises(extract.SyncError, match="run with --full"):
            run_sync(odb, oracle_settings)
        assert int(scalar(odb, "SELECT COUNT(*) FROM graph_sync_runs")) == before

        full = run_sync(odb, oracle_settings, full=True)
        assert full.mode == "FULL"
        assert full.source_backend == "oracle"
        assert full.source_user == "aml_graph_sync_usr"
        assert full.sent == s11(*TINY_S11)
        assert full.graph == s11(*TINY_S11)
        assert full.source == {"TRANSFERRED_TO": 3651, "SENT_TO": 3575}
        assert full.watermark_to == datetime(2026, 6, 30, 21, 53, 57)
        assert full.in_sync is True
        assert graph_snapshot(d, s) == from_duck

        inc = run_sync(odb, oracle_settings)
        assert inc.mode == "INCREMENTAL"
        assert inc.since == datetime(2026, 6, 30, 20, 53, 57)
        assert inc.sent["TRANSFERRED_TO"] == 1
        assert inc.sent["SENT_TO"] == 19
        assert inc.graph == full.graph
        assert inc.in_sync is True

        runs = odb.query_df(
            "SELECT run_id, source_user, in_sync FROM graph_sync_runs ORDER BY run_id DESC"
        ).head(2)
        assert list(runs["source_user"]) == ["aml_graph_sync_usr"] * 2
        assert [int(v) for v in runs["in_sync"]] == [1, 1]
        views = set(odb.query_df("SELECT view_name FROM user_views")["view_name"])
        assert "GRAPH_CUSTOMER_ATTRS" in views

    with admin_db() as adm:
        tab = adm.query_df(
            "SELECT privilege, table_name FROM dba_tab_privs "
            f"WHERE grantee = 'AML_GRAPH_SYNC' AND owner = '{owner.upper()}'"
        )
    assert set(zip(tab["privilege"], tab["table_name"], strict=True)) == GRAPH_SYNC_GRANTS

    with demo_db("aml_graph_sync") as sync_user:
        for table in ("graph_customer_attrs", "customer_golden"):
            assert int(scalar(sync_user, f"SELECT COUNT(*) FROM {owner}.{table}")) == 300, table
        for table in ("customers", "audit_log"):
            _fails(sync_user, f"SELECT COUNT(*) FROM {owner}.{table}", "ORA-00942")
        _fails(sync_user, f"DELETE FROM {owner}.transactions", "ORA-01031|ORA-41900")

    with OracleDb(oracle_settings) as odb:
        mod("aml.dba.schema").apply_schema(odb)
