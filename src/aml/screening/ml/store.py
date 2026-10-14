"""Small helpers shared by the screening-ML modules: named SQL files, ids, JSON/CLOB values."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from aml.common.db import Database

VERSION = "screening-ml/v1"  # version of the label / feature steps on audit rows
TABLES = (
    "screening_ml_labels",
    "screening_ml_features",
    "screening_ml_models",
    "screening_ml_scores",
)


def schema_ready(db: Database) -> bool:
    """True when the DDL 210 tables exist; any other database error is not swallowed."""
    names = ", ".join(f"'{t.upper() if db.backend == 'oracle' else t}'" for t in TABLES)
    source = "user_tables" if db.backend == "oracle" else "information_schema.tables"
    n = db.query_df(f"SELECT COUNT(*) FROM {source} WHERE table_name IN ({names})").iloc[0, 0]
    return int(n) == len(TABLES)


def require_schema(db: Database) -> None:
    from aml.screening.ml.model import ScreeningMlError  # model.py is pure; imported lazily

    if not schema_ready(db):
        raise ScreeningMlError("screening-ml tables are missing; run `aml init-db` first")


def run_query(db: Database, name: str, **ints: int) -> pd.DataFrame:
    """Run ``sql/<backend>|common/screening_ml/<name>.sql``; ``{key}`` becomes the integer value.

    Column names come back in lower case on both backends.
    """
    sql = db.sql_file(f"screening_ml/{name}.sql").read_text(encoding="utf-8")
    for key, value in ints.items():
        sql = sql.replace("{" + key + "}", str(int(value)))
    df = db.query_df(sql)
    df.columns = [str(c).lower() for c in df.columns]
    return df


def next_id(db: Database, table: str, column: str) -> int:
    """``MAX + 1`` of an id column (the commands do not run concurrently)."""
    return 1 + int(db.query_df(f"SELECT COALESCE(MAX({column}), 0) FROM {table}").iloc[0, 0])


def count(db: Database, table: str) -> int:
    return int(db.query_df(f"SELECT COUNT(*) FROM {table}").iloc[0, 0])


def text(value: Any) -> str:
    """A CLOB column as text (DuckDB returns str, Oracle a LOB)."""
    return str(value.read()) if hasattr(value, "read") else str(value)


def json_value(value: Any) -> Any:
    """A JSON column: DuckDB and Oracle both give text (Oracle may give a LOB), parsed here."""
    return json.loads(text(value)) if isinstance(value, str) or hasattr(value, "read") else value
