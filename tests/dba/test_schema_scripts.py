"""Acceptance test AC1 for specs/oracle-schema-core.md (static checks, no Oracle needed)."""

from __future__ import annotations

import importlib
import re
from typing import Any

from aml.common.db import SQL_ROOT, split_oracle_script, sql_file


def _strip_comments(stmt: str) -> str:
    return "\n".join(ln for ln in stmt.splitlines() if not ln.strip().startswith("--")).strip()


def test_ac1_oracle_scripts_split_and_ddl_is_wrapped_in_plsql_blocks() -> None:
    files = sorted((SQL_ROOT / "oracle").rglob("*.sql"))
    assert files
    for path in files:
        statements = split_oracle_script(path.read_text(encoding="utf-8"))
        assert len(statements) >= 1, path.name
        for stmt in statements:
            body = _strip_comments(stmt)
            assert not re.match(r"(?i)(CREATE|ALTER|DROP)\b", body), f"{path.name}: bare DDL"


def test_ac1_schema_scripts_resolve_to_backend_directory() -> None:
    schema: Any = importlib.import_module("aml.dba.schema")
    scripts = schema.SCHEMA_SCRIPTS
    for backend in ("oracle", "duckdb"):
        assert scripts[backend]
        for name in scripts[backend]:
            resolved = sql_file(name, backend)
            assert resolved.parent.parent == SQL_ROOT / backend, (backend, name)
            assert resolved.is_file()
    assert "ddl/020_transactions_partitioning.sql" in scripts["oracle"]
    assert "ddl/040_acct_edge_daily.sql" in scripts["duckdb"]
