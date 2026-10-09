import logging

import pandas as pd
import pytest

from aml.common.config import load_settings
from aml.common.db import (
    DuckDb,
    OracleDb,
    get_db,
    split_oracle_script,
    sql_file,
)


def test_split_oracle_script_handles_plsql_and_comments() -> None:
    script = """
-- comment
CREATE TABLE t (x NUMBER)
/
BEGIN
  NULL; -- semicolons inside PL/SQL must not split
END;
/
-- trailing comment only
"""
    stmts = split_oracle_script(script)
    assert len(stmts) == 2
    assert stmts[1].startswith("BEGIN") and stmts[1].endswith("END;")


def test_split_oracle_script_rejects_unterminated_statement() -> None:
    with pytest.raises(ValueError, match="without a '/'"):
        split_oracle_script("SELECT 1 FROM dual")


def test_sql_file_resolves_per_backend() -> None:
    assert sql_file("ddl/000_audit_log.sql", "oracle").parent.parent.name == "oracle"
    assert sql_file("ddl/000_audit_log.sql", "duckdb").parent.parent.name == "duckdb"
    with pytest.raises(FileNotFoundError):
        sql_file("ddl/does_not_exist.sql", "duckdb")


def test_duckdb_insert_and_query_roundtrip(duck: DuckDb) -> None:
    duck.execute("CREATE TABLE t (id INTEGER, name VARCHAR)")
    df = pd.DataFrame({"name": ["Nguyễn Văn A", None], "id": [1, 2]})  # column order differs
    assert duck.insert_df("t", df) == 2
    out = duck.query_df("SELECT id, name FROM t ORDER BY id")
    assert out["name"].tolist()[0] == "Nguyễn Văn A"
    assert pd.isna(out["name"].iloc[1])


def test_oracle_down_falls_back_to_duckdb(tmp_path, caplog) -> None:
    s = load_settings(
        environ={
            "DB_BACKEND": "oracle",
            "AML__DB__ORACLE__PORT": "1",  # nothing listens here
            "ORACLE_APP_PASSWORD": "x",
            "AML__DB__DUCKDB_PATH": str(tmp_path / "fb.duckdb"),
        }
    )
    with caplog.at_level(logging.WARNING), get_db(s) as db:
        assert db.backend == "duckdb"
    assert "falling back to DuckDB" in caplog.text


def test_oracle_down_without_fallback_raises(tmp_path) -> None:
    from aml.common.db import ServiceUnavailableError

    s = load_settings(
        environ={
            "DB_BACKEND": "oracle",
            "AML__DB__ORACLE__PORT": "1",
            "ORACLE_APP_PASSWORD": "x",
            "AML__DB__FALLBACK_TO_DUCKDB": "false",
        }
    )
    with pytest.raises(ServiceUnavailableError):
        get_db(s)


@pytest.mark.oracle
def test_oracle_connect_and_query() -> None:
    with OracleDb(load_settings()) as db:
        assert db.query_df("SELECT 1 AS one FROM dual")["one"].iloc[0] == 1
