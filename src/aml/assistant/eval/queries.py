"""Read-only SQL of the evaluation: ``sql/common/assistant_eval/*.sql``, shared by both backends."""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any

import pandas as pd

from aml.common.db import Database

SAFE_ID = re.compile(r"[A-Z0-9-]{1,60}")  # the only text ever put into a statement
BATCH = 500  # ids per IN list (Oracle allows 1000)


def read(db: Database, name: str, **placeholders: str) -> list[dict[str, Any]]:
    """Rows of the single SELECT in ``assistant_eval/<name>.sql`` as dicts with lower-case keys."""
    text = db.sql_file(f"assistant_eval/{name}.sql").read_text(encoding="utf-8")
    statement = text.strip().rstrip(";")
    for key, value in placeholders.items():
        statement = statement.replace("{" + key + "}", value)
    frame = db.query_df(statement)
    frame.columns = [str(c).lower() for c in frame.columns]
    return [{k: _plain(v) for k, v in row.items()} for row in frame.to_dict("records")]


def _plain(value: Any) -> Any:
    """NULL / NaN / NaT become None; pandas timestamps become ``datetime``."""
    if value is None or (not isinstance(value, str) and bool(pd.isna(value))):
        return None
    return value.to_pydatetime() if isinstance(value, pd.Timestamp) else value


def counts(db: Database, name: str) -> dict[str, int]:
    """A ``name, n`` result as a dict (row counts of several tables in one statement)."""
    return {str(row["name"]): int(row["n"]) for row in read(db, name)}


def existing_ids(db: Database, candidates: Collection[str]) -> set[str]:
    """The candidates that exist as a transaction, account, customer, case or watchlist id."""
    safe = sorted(c for c in set(candidates) if SAFE_ID.fullmatch(c))
    found: set[str] = set()
    for start in range(0, len(safe), BATCH):
        literals = ", ".join(f"'{c}'" for c in safe[start : start + BATCH])
        found.update(str(row["id"]) for row in read(db, "known_ids", ids=literals))
    return found
