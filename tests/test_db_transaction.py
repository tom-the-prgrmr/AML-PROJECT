"""`Database.transaction()`: writes inside the block commit together or not at all."""

from __future__ import annotations

import uuid

import pandas as pd
import pytest

from aml.common.audit import audit
from aml.common.config import load_settings, read_environ
from aml.common.db import DuckDb, OracleDb


def _count(db: DuckDb) -> int:
    return int(db.query_df("SELECT COUNT(*) FROM t").iloc[0, 0])


def test_duckdb_commits_both_writes_together(duck: DuckDb) -> None:
    duck.execute("CREATE TABLE t (n INTEGER)")
    with duck.transaction():
        duck.insert_df("t", pd.DataFrame({"n": [1, 2]}))
        duck.execute("INSERT INTO t VALUES (3)")
    assert _count(duck) == 3


def test_duckdb_rolls_back_every_write_when_the_block_fails(duck: DuckDb) -> None:
    duck.execute("CREATE TABLE t (n INTEGER)")
    duck.execute("INSERT INTO t VALUES (0)")  # committed on its own, outside the block
    with pytest.raises(RuntimeError, match="boom"), duck.transaction():
        duck.insert_df("t", pd.DataFrame({"n": [1, 2]}))
        raise RuntimeError("boom")
    assert _count(duck) == 1
    duck.execute("INSERT INTO t VALUES (9)")  # the connection is usable again
    assert _count(duck) == 2


@pytest.mark.oracle
def test_oracle_rolls_back_and_then_autocommits_again() -> None:
    settings = load_settings(environ={**read_environ(), "DB_BACKEND": "oracle"})
    marker = f"tx-{uuid.uuid4().hex}"  # audit_log is append-only: find our rows by a fresh id

    def rows(db: OracleDb) -> int:
        sql = f"SELECT COUNT(*) FROM audit_log WHERE entity_id = '{marker}'"
        return int(db.query_df(sql).iloc[0, 0])

    def write(db: OracleDb) -> None:
        audit(
            db, module="test", entity_type="probe", entity_id=marker, decision="PROBE", reason="x"
        )

    with OracleDb(settings) as db:
        with pytest.raises(RuntimeError, match="boom"), db.transaction():
            write(db)
            raise RuntimeError("boom")
        assert rows(db) == 0
        with db.transaction():
            write(db)
            write(db)
    with OracleDb(settings) as db:  # a new connection only sees committed rows
        assert rows(db) == 2
