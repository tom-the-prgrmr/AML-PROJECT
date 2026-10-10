"""Acceptance tests AC4-AC8 for specs/oracle-schema-core.md (need a running Oracle)."""

from __future__ import annotations

import contextlib
import importlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import DuckDb, OracleDb
from tests.datagen.conftest import EnvFactory

from .conftest import TABLES, audit_rows

pytestmark = pytest.mark.oracle

CONSTRAINTS = [
    "FK_ACCOUNTS_CUSTOMER",
    "FK_CP_CUSTOMER",
    "FK_WLA_WATCHLIST",
    "CK_TXN_AMOUNT_POS",
    "CK_TXN_CHANNEL",
    "CK_TXN_HAS_PARTY",
]


def _oracle_settings(tiny_env: EnvFactory) -> Settings:
    return load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle")})


def _mod(name: str) -> Any:
    return importlib.import_module(name)


def _scalar(db: OracleDb, sql: str) -> Any:
    return db.query_df(sql).iloc[0, 0]


def _count_audit(db: OracleDb, decision: str, entity_id: str | None = None) -> int:
    where = f"module = 'dba' AND decision = '{decision}'"
    if entity_id:
        where += f" AND entity_id = '{entity_id}'"
    return len(audit_rows(db, where))


def _constraints_ok(db: OracleDb) -> None:
    df = db.query_df("SELECT constraint_name, status, validated FROM user_constraints")
    by_name = {r.constraint_name: (r.status, r.validated) for r in df.itertuples()}
    for name in CONSTRAINTS:
        assert by_name.get(name) == ("ENABLED", "VALIDATED"), name


def test_ac4_apply_schema_converts_heap_transactions_to_interval_partitioned(
    tiny_env: EnvFactory,
) -> None:
    schema = _mod("aml.dba.schema")
    with OracleDb(_oracle_settings(tiny_env)) as db:
        schema.apply_schema(db)  # make sure audit_log etc. exist
        for stmt in ("DROP MATERIALIZED VIEW acct_edge_daily", "DROP TABLE transactions PURGE"):
            with contextlib.suppress(Exception):  # object may not exist yet
                db.execute(stmt)
        db.run_named_script("ddl/010_datagen.sql")  # heap table, as in Phase 1
        for ts in ("2026-01-15", "2026-02-15", "2026-03-15"):
            db.execute(
                "INSERT INTO transactions (txn_id, txn_ts, from_account_id, amount_vnd, "
                f"channel) VALUES ('P{ts}', TIMESTAMP '{ts} 10:00:00', 'A1', 1000, 'CASH')"
            )
        before = _count_audit(db, "PARTITIONED", "transactions")

        schema.apply_schema(db)
        schema.apply_schema(db)

        part = db.query_df(
            'SELECT partitioning_type, "INTERVAL" AS iv FROM user_part_tables '
            "WHERE table_name = 'TRANSACTIONS'"
        ).iloc[0]
        assert part["partitioning_type"] == "RANGE"
        assert part["iv"].replace(" ", "") == "NUMTOYMINTERVAL(1,'MONTH')"
        keys = db.query_df(
            "SELECT column_name FROM user_part_key_columns "
            "WHERE name = 'TRANSACTIONS' AND object_type = 'TABLE' ORDER BY column_position"
        )
        assert list(keys["column_name"]) == ["TXN_TS"]
        nullable = _scalar(
            db,
            "SELECT nullable FROM user_tab_cols "
            "WHERE table_name = 'TRANSACTIONS' AND column_name = 'TXN_TS'",
        )
        assert nullable == "N"
        assert int(_scalar(db, "SELECT COUNT(*) FROM transactions")) == 3
        assert _count_audit(db, "PARTITIONED", "transactions") == before + 1


def test_ac5_indexes_and_constraints_exist_after_apply_schema(tiny_env: EnvFactory) -> None:
    schema = _mod("aml.dba.schema")
    with OracleDb(_oracle_settings(tiny_env)) as db:
        schema.apply_schema(db)

        local = db.query_df(
            "SELECT index_name, locality FROM user_part_indexes WHERE table_name = 'TRANSACTIONS'"
        )
        loc = dict(zip(local["index_name"], local["locality"], strict=True))
        assert loc.get("IX_TXN_FROM_TS") == "LOCAL"
        assert loc.get("IX_TXN_TO_TS") == "LOCAL"
        cols = db.query_df(
            "SELECT index_name, column_name FROM user_ind_columns "
            "WHERE index_name IN ('IX_TXN_FROM_TS', 'IX_TXN_TO_TS') ORDER BY column_position"
        )
        order = {n: list(g["column_name"]) for n, g in cols.groupby("index_name")}
        assert order["IX_TXN_FROM_TS"] == ["FROM_ACCOUNT_ID", "TXN_TS"]
        assert order["IX_TXN_TO_TS"] == ["TO_ACCOUNT_ID", "TXN_TS"]

        pk = db.query_df(
            "SELECT i.partitioned FROM user_indexes i JOIN user_constraints c "
            "ON c.index_name = i.index_name WHERE c.table_name = 'TRANSACTIONS' "
            "AND c.constraint_type = 'P'"
        )
        assert list(pk["partitioned"]) == ["NO"]

        existing = set(db.query_df("SELECT index_name FROM user_indexes")["index_name"])
        for name in ("IX_ACCOUNTS_CIF", "IX_WLA_ENTRY", "IX_CP_PERSON"):
            assert name in existing, name
        for name in ("IX_AED_SRC_DAY", "IX_AED_DST_DAY"):
            assert name in existing, name
        _constraints_ok(db)


def test_ac6_load_twice_keeps_constraints_and_rejects_bad_rows(
    tiny_env: EnvFactory, tiny_parquet: Path
) -> None:
    load_mod = _mod("aml.datagen.load")
    manifest = json.loads((tiny_parquet / "manifest.json").read_text(encoding="utf-8"))
    with OracleDb(_oracle_settings(tiny_env)) as db:
        for _ in range(2):
            load_mod.load_parquet(db, tiny_parquet)
        for t in TABLES:
            assert int(_scalar(db, f"SELECT COUNT(*) FROM {t}")) == manifest["tables"][t], t
        _constraints_ok(db)

        with pytest.raises(Exception, match="ORA-02290"):
            db.execute(
                "INSERT INTO transactions (txn_id, txn_ts, from_account_id, amount_vnd, "
                "channel) VALUES ('T_BAD0', TIMESTAMP '2026-01-15 10:00:00', 'A1', 0, 'CASH')"
            )
        with pytest.raises(Exception, match="ORA-02291"):
            db.execute("INSERT INTO accounts (account_id, cif) VALUES ('ACC_BAD', 'C_NOT_EXIST')")


def test_ac7_load_gathers_stats_and_audits(tiny_env: EnvFactory, tiny_parquet: Path) -> None:
    load_mod = _mod("aml.datagen.load")
    manifest = json.loads((tiny_parquet / "manifest.json").read_text(encoding="utf-8"))
    with OracleDb(_oracle_settings(tiny_env)) as db:
        before = _count_audit(db, "STATS_GATHERED")
        load_mod.load_parquet(db, tiny_parquet)

        stats = db.query_df(
            "SELECT table_name, last_analyzed, num_rows FROM user_tab_statistics "
            "WHERE partition_name IS NULL"
        )
        by_table = {r.table_name: r for r in stats.itertuples()}
        for t in [*TABLES, "acct_edge_daily"]:
            row = by_table.get(t.upper())
            assert row is not None and pd.notna(row.last_analyzed), t
        assert int(by_table["TRANSACTIONS"].num_rows) == manifest["tables"]["transactions"]

        prefs = _scalar(
            db, "SELECT DBMS_STATS.GET_PREFS('INCREMENTAL', USER, 'TRANSACTIONS') FROM dual"
        )
        assert prefs == "TRUE"
        populated = _scalar(
            db,
            "SELECT COUNT(*) FROM user_tab_partitions "
            "WHERE table_name = 'TRANSACTIONS' AND num_rows > 0",
        )
        assert int(populated) == 6

        rows = audit_rows(db, "module = 'dba' AND decision = 'STATS_GATHERED'")
        assert len(rows) == before + 1
        tables = rows.iloc[-1]["details"]["tables"]
        assert len(tables) == 10
        assert {t.upper() for t in tables} == {t.upper() for t in [*TABLES, "acct_edge_daily"]}


def test_ac8_acct_edge_daily_is_a_complete_mview_equal_to_duckdb(
    tiny_env: EnvFactory, tiny_parquet: Path, tmp_path: Path
) -> None:
    load_mod = _mod("aml.datagen.load")
    sql = "SELECT src_acct, dst_acct, day, txn_count, total_amount FROM acct_edge_daily"

    def normalise(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        df["day"] = pd.to_datetime(df["day"]).dt.date
        df["txn_count"] = df["txn_count"].astype("int64")
        df["total_amount"] = df["total_amount"].astype("int64")
        return df.sort_values(["src_acct", "dst_acct", "day"]).reset_index(drop=True)

    with OracleDb(_oracle_settings(tiny_env)) as odb:
        load_mod.load_parquet(odb, tiny_parquet)
        method = _scalar(
            odb, "SELECT refresh_method FROM user_mviews WHERE mview_name = 'ACCT_EDGE_DAILY'"
        )
        assert method == "COMPLETE"
        oracle_df = normalise(odb.query_df(sql))
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        load_mod.load_parquet(ddb, tiny_parquet)
        duck_df = normalise(ddb.query_df(sql))

    assert len(oracle_df) > 0
    pd.testing.assert_frame_equal(oracle_df, duck_df)
