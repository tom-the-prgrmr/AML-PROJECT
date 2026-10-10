"""AC3-AC4 for specs/oracle-security.md (static checks and CLI guards, no Oracle needed)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from aml.common.config import get_settings, load_settings
from aml.common.db import SQL_ROOT, split_oracle_script, sql_file

from .helpers import mod

SECURITY_SCRIPTS = (
    "security/010_roles_users.sql",
    "security/020_grants.sql",
    "security/030_audit_policies.sql",
)


def test_ac3_security_scripts_resolve_and_split() -> None:
    for name in SECURITY_SCRIPTS:
        path = sql_file(name, "oracle")
        assert path.is_file(), name
        statements = split_oracle_script(path.read_text(encoding="utf-8"))
        assert len(statements) >= 1, name


def test_ac3_schema_scripts_end_with_security_objects() -> None:
    scripts = mod("aml.dba.schema").SCHEMA_SCRIPTS
    assert scripts["oracle"][-1] == "ddl/050_security_objects.sql"
    assert scripts["duckdb"][-1] == "ddl/050_customers_masked.sql"
    for name in SECURITY_SCRIPTS:
        assert name not in scripts["oracle"]


def test_ac3_no_password_in_sql_files() -> None:
    files = [p for p in SQL_ROOT.rglob("*") if p.is_file()]
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8").upper()
        assert "IDENTIFIED BY" not in text, path


def test_ac3_config_defaults_and_secret_mapping() -> None:
    cfg = load_settings(environ={}).db.oracle
    assert cfg.admin_user == "system"
    assert cfg.admin_password == ""
    assert cfg.demo_password == ""
    cfg = load_settings(
        environ={"ORACLE_SYS_PASSWORD": "s1", "ORACLE_DEMO_PASSWORD": "d1"}
    ).db.oracle
    assert cfg.admin_password == "s1"
    assert cfg.demo_password == "d1"


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    """Apply env overrides, forbid any Oracle connection, and reset the settings cache."""
    import oracledb

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("oracledb.connect must not be called")

    monkeypatch.setattr(oracledb, "connect", forbidden)

    def apply(**env: str) -> None:
        monkeypatch.setenv("AML__DB__DUCKDB_PATH", str(tmp_path / "x.duckdb"))
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def _run() -> Result:
    return CliRunner().invoke(mod("aml.cli").app, ["security-setup"])


def test_ac4_security_setup_on_duckdb_exits_2(cli_env: Callable[..., None]) -> None:
    cli_env(DB_BACKEND="duckdb", ORACLE_SYS_PASSWORD="s1", ORACLE_DEMO_PASSWORD="d1")
    result = _run()
    assert result.exit_code == 2, result.output
    assert "Oracle only" in result.output


def test_ac4_security_setup_without_sys_password_exits_2(cli_env: Callable[..., None]) -> None:
    cli_env(DB_BACKEND="oracle", ORACLE_SYS_PASSWORD="", ORACLE_DEMO_PASSWORD="d1")
    result = _run()
    assert result.exit_code == 2, result.output
    assert "ORACLE_SYS_PASSWORD" in result.output


@pytest.mark.parametrize("demo", ["", 'a"b'])
def test_ac4_security_setup_with_bad_demo_password_exits_2(
    cli_env: Callable[..., None], demo: str
) -> None:
    cli_env(DB_BACKEND="oracle", ORACLE_SYS_PASSWORD="s1", ORACLE_DEMO_PASSWORD=demo)
    result = _run()
    assert result.exit_code == 2, result.output
    assert "ORACLE_DEMO_PASSWORD" in result.output
