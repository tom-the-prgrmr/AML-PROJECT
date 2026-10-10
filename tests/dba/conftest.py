"""Shared fixtures for the Phase 2a tests (specs/oracle-schema-core.md).

Re-uses the TINY fixtures of the Phase 1c tests and adds small helpers.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from aml.common.db import Database
from tests.datagen.conftest import TABLES, tiny_env, tiny_parquet, tiny_settings

__all__ = ["TABLES", "audit_rows", "tiny_env", "tiny_parquet", "tiny_settings"]


def audit_rows(db: Database, where: str) -> pd.DataFrame:
    """audit_log rows matching ``where`` with ``details`` parsed into a dict (or None)."""
    expr = "JSON_SERIALIZE(details)" if db.backend == "oracle" else "details"
    df = db.query_df(
        f"SELECT module, entity_type, entity_id, decision, {expr} AS details "
        f"FROM audit_log WHERE {where} ORDER BY audit_id"
    )
    df.columns = [c.lower() for c in df.columns]
    parsed: list[Any] = [json.loads(d) if isinstance(d, str) else d for d in df["details"]]
    df["details"] = parsed
    return df
