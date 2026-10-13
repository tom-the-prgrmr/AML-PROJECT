"""AC4 (Oracle part) for specs/neo4j-gds.md: the same features from an Oracle-sourced graph.

Needs Oracle, Neo4j, ORACLE_SYS_PASSWORD and ORACLE_DEMO_PASSWORD. Like the earlier Oracle tests it
reloads TINY into the schema owner and re-applies the grants; it leaves rows in `gds_runs`,
`gds_account_features`, `graph_sync_runs` and `audit_log`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import DuckDb, OracleDb
from tests.security.helpers import admin_db

from .conftest import Neo
from .helpers import (
    TINY_S11,
    VALUE_COLUMNS,
    feature_frame,
    mod,
    neo_settings,
    none_if_nan,
    run_gds,
    run_sync,
    s11,
)

pytestmark = [pytest.mark.oracle, pytest.mark.neo4j]

ROLES = ("AML_APP", "AML_ANALYST", "AML_GRAPH_SYNC", "AML_AUDITOR")


@pytest.fixture
def oracle_settings() -> Settings:
    env = {**read_environ(), "DB_BACKEND": "oracle"}
    for name in ("ORACLE_SYS_PASSWORD", "ORACLE_DEMO_PASSWORD"):
        if not env.get(name):
            pytest.skip(f"{name} is not set in .env")
    return load_settings(environ=env)


def test_ac4_oracle_gds_matches_duckdb_gds(
    neo: Neo, oracle_settings: Settings, tiny_parquet: Path, er_template: Path, tmp_path: Path
) -> None:
    load = mod("aml.datagen.load")
    assert neo.driver is not None  # the fixture wipes the projection first
    dsettings = neo_settings()

    # DuckDB reference run on the same TINY.
    path = tmp_path / "tiny.duckdb"
    shutil.copy(er_template, path)
    with DuckDb(path) as ddb:
        assert run_sync(ddb, dsettings, full=True).graph == s11(*TINY_S11)
        duck_run = run_gds(ddb, dsettings)
        duck_rows = feature_frame(ddb, duck_run.run_id)

    with OracleDb(oracle_settings) as odb:
        load.load_parquet(odb, tiny_parquet)
        mod("aml.entity_resolution.runner").run_er(odb, oracle_settings)
    mod("aml.dba.security").apply_security(oracle_settings)

    with OracleDb(oracle_settings) as odb:
        assert run_sync(odb, oracle_settings, full=True).source_backend == "oracle"
        run = run_gds(odb, oracle_settings)

        tables = set(odb.query_df("SELECT table_name FROM user_tables")["table_name"])
        views = set(odb.query_df("SELECT view_name FROM user_views")["view_name"])
        assert {"GDS_RUNS", "GDS_ACCOUNT_FEATURES"} <= tables
        assert "GDS_ACCOUNT_FEATURES_CURRENT" in views

        assert run.accounts == 532
        assert run.active_accounts == 298
        assert run.wcc_components == 9
        assert run.louvain_communities == 20
        assert run.shared_clusters == 2

        current = feature_frame(odb, None, "gds_account_features_current")
        assert len(current) == 532
        assert list(current["account_id"]) == list(duck_rows["account_id"])
        for column in VALUE_COLUMNS:
            if column == "pagerank":
                diff = (current[column].astype(float) - duck_rows[column].astype(float)).abs()
                assert diff.max() <= 1e-9
            else:
                assert [none_if_nan(v) for v in current[column]] == [
                    none_if_nan(v) for v in duck_rows[column]
                ], column

        runs = odb.query_df("SELECT source_backend FROM gds_runs WHERE run_id = " + str(run.run_id))
        assert runs.iloc[0, 0] == "oracle"

        with DuckDb(tmp_path / "empty.duckdb") as empty:
            mod("aml.dba.schema").apply_schema(empty)
            with pytest.raises(
                mod("aml.graph.neo4j.gds").GdsError,
                match="graph was synced from oracle but the database is duckdb",
            ):
                run_gds(empty, dsettings)

    roles = ", ".join(f"'{r}'" for r in ROLES)
    with admin_db() as adm:
        privs = adm.query_df(
            "SELECT grantee, table_name FROM dba_tab_privs WHERE table_name IN "
            f"('GDS_RUNS', 'GDS_ACCOUNT_FEATURES') AND grantee IN ({roles})"
        )
    assert len(privs) == 0

    with OracleDb(oracle_settings) as odb:
        mod("aml.dba.schema").apply_schema(odb)
