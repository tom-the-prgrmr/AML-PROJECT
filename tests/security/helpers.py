"""Helpers for the Phase 2b tests: settings and logins for admin, owner and demo users."""

from __future__ import annotations

import importlib
from typing import Any

import pandas as pd

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import OracleDb

ROLES = ("aml_app", "aml_analyst", "aml_graph_sync", "aml_auditor")


def mod(name: str) -> Any:
    return importlib.import_module(name)


def base_env() -> dict[str, str]:
    return {**read_environ(), "DB_BACKEND": "oracle"}


def owner_settings() -> Settings:
    return load_settings(environ=base_env())


def settings_for(user: str, password: str) -> Settings:
    env = {**base_env(), "ORACLE_APP_USER": user, "ORACLE_APP_PASSWORD": password}
    return load_settings(environ=env)


def admin_db() -> OracleDb:
    env = base_env()
    admin_user = owner_settings().db.oracle.admin_user
    return OracleDb(settings_for(admin_user, env["ORACLE_SYS_PASSWORD"]))


def demo_db(role: str) -> OracleDb:
    return OracleDb(settings_for(f"{role}_usr", base_env()["ORACLE_DEMO_PASSWORD"]))


def scalar(db: OracleDb, sql: str) -> Any:
    return db.query_df(sql).iloc[0, 0]


def normalise_masked(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    out["birth_year"] = out["birth_year"].astype("Int64")
    return out.reset_index(drop=True)
