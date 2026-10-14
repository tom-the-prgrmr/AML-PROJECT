"""Helpers for the Phase 9a tests (specs/ui-foundation.md).

``fastapi`` / ``starlette`` / ``aml.api`` are imported lazily so that the rest of the suite still
collects before the API exists and every test fails for its own reason.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
from typer.testing import CliRunner

from aml.common.config import Settings, load_settings
from aml.common.db import Database

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "src" / "aml" / "api"
WEB = ROOT / "web"
PREFIX = "/api/v1"
CASE_C01_A = "C-C01-20260302"
CASE_C05 = "C-C05-20260630"
MINI_ORDER = [
    "C-C01-20260531",
    "C-C05-20260630",
    "C-C01-20260302",
    "C-C03-20260305",
    "C-C04-20260305",
]
CASE_KEYS = {
    "case_id",
    "golden_customer_id",
    "status",
    "alerts",
    "rule_alerts",
    "network_alerts",
    "screening_alerts",
    "sources",
    "window_start",
    "first_alert_ts",
    "last_alert_ts",
    "reason",
    "disposition",
}


def mod(name: str) -> Any:
    return importlib.import_module(name)


def api_settings(**env: str) -> Settings:
    return load_settings(environ={"DB_BACKEND": "duckdb", **env})


def make_client(db: Database | None, settings: Settings, user: str | None = None) -> Any:
    """``TestClient(create_app(settings, db=db))``; every request carries ``X-AML-User: user``."""
    from starlette.testclient import TestClient

    app = mod("aml.api.app").create_app(settings, db=db)
    headers = {"X-AML-User": user} if user is not None else {}
    return TestClient(app, headers=headers, raise_server_exceptions=False)


def query(db: Database, sql: str) -> pd.DataFrame:
    df = db.query_df(sql)
    df.columns = [c.lower() for c in df.columns]
    return df


def count(db: Database, table: str, where: str = "") -> int:
    return int(db.query_df(f"SELECT COUNT(*) FROM {table} {where}").iloc[0, 0])


def js(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def audit_rows(db: Database, where: str) -> list[dict[str, Any]]:
    df = query(
        db,
        "SELECT module, entity_type, entity_id, decision, reason, version, actor, details "
        f"FROM audit_log WHERE {where} ORDER BY audit_id",
    )
    rows = df.to_dict("records")
    for row in rows:
        row["details"] = js(row["details"])
    return rows


def error_of(resp: Any) -> dict[str, Any]:
    return resp.json()["error"]


def aml_cli(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, list(args))


class FakeDb:
    """A Database whose every read raises ``exc``; used to prove the error envelope."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def query_df(self, *args: Any, **kw: Any) -> Any:
        raise self.exc

    def execute(self, *args: Any, **kw: Any) -> Any:
        raise self.exc

    def run_script(self, *args: Any, **kw: Any) -> Any:
        raise self.exc

    def insert_df(self, *args: Any, **kw: Any) -> Any:
        raise self.exc

    def close(self) -> None:
        return None
