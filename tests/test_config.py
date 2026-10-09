from datetime import date

import pytest

from aml.common.config import apply_env_overrides, load_settings, read_environ


def test_defaults_load_and_validate() -> None:
    s = load_settings(environ={})
    assert s.db.backend == "duckdb"
    assert s.data.profile == "small"
    assert s.data.active.customers == 5000
    assert s.thresholds.large_cash_vnd == 400_000_000


def test_nested_env_override_is_yaml_typed() -> None:
    s = load_settings(environ={"AML__THRESHOLDS__LARGE_CASH_VND": "300000000"})
    assert s.thresholds.large_cash_vnd == 300_000_000


def test_reference_date_default() -> None:
    assert load_settings(environ={}).data.reference_date == date(2026, 6, 30)


def test_reference_date_env_override() -> None:
    s = load_settings(environ={"AML__DATA__REFERENCE_DATE": "2027-01-01"})
    assert s.data.reference_date == date(2027, 1, 1)


def test_start_date_and_injection_memos_defaults() -> None:
    s = load_settings(environ={})
    assert s.data.start_date == date(2026, 1, 1)
    assert s.data.injection_memos == 30


def test_start_date_env_override() -> None:
    s = load_settings(environ={"AML__DATA__START_DATE": "2025-07-01"})
    assert s.data.start_date == date(2025, 7, 1)


def test_db_backend_shortcut() -> None:
    s = load_settings(environ={"DB_BACKEND": "ORACLE"})
    assert s.db.backend == "oracle"


def test_profile_switch_changes_active_profile() -> None:
    s = load_settings(environ={"AML__DATA__PROFILE": "dense"})
    assert s.data.active.counterparties == (50, 100)


def test_secrets_not_in_yaml_and_come_from_env() -> None:
    assert load_settings(environ={}).db.oracle.password == ""
    s = load_settings(
        environ={"ORACLE_APP_USER": "u1", "ORACLE_APP_PASSWORD": "p@ss:1", "NEO4J_PASSWORD": "n"}
    )
    assert (s.db.oracle.user, s.db.oracle.password, s.neo4j.password) == ("u1", "p@ss:1", "n")


def test_process_env_wins_over_dotenv(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("ORACLE_APP_PASSWORD=from_file\nNEO4J_PASSWORD=file_neo\n", encoding="utf-8")
    monkeypatch.setenv("ORACLE_APP_PASSWORD", "from_process")
    env = read_environ(dotenv)
    assert env["ORACLE_APP_PASSWORD"] == "from_process"
    assert env["NEO4J_PASSWORD"] == "file_neo"


def test_missing_password_is_a_clear_error() -> None:
    from aml.common.db import OracleDb, ServiceUnavailableError

    with pytest.raises(ServiceUnavailableError, match="ORACLE_APP_PASSWORD"):
        OracleDb(load_settings(environ={}))


def test_unrelated_env_vars_ignored() -> None:
    raw = apply_env_overrides({"seed": 1}, {"PATH": "x", "AML_NOT_PREFIXED": "y"})
    assert raw == {"seed": 1}


def test_typology_defaults() -> None:
    s = load_settings(environ={})
    assert s.data.typologies == {
        "structuring": 20,
        "rapid_movement": 20,
        "mule_ring": 5,
        "round_tripping": 15,
        "benign_payroll": 5,
        "benign_merchant": 5,
    }
    assert s.data.active.typology_scale == 1


def test_typology_scale_large_profile() -> None:
    s = load_settings(environ={"AML__DATA__PROFILE": "large"})
    assert s.data.active.typology_scale == 10
    assert load_settings(environ={}).data.profiles["dense"].typology_scale == 1


def test_typology_env_override() -> None:
    s = load_settings(environ={"AML__DATA__TYPOLOGIES__STRUCTURING": "3"})
    assert s.data.typologies["structuring"] == 3
    assert s.data.typologies["mule_ring"] == 5
