from aml.common.config import apply_env_overrides, load_settings


def test_defaults_load_and_validate() -> None:
    s = load_settings(environ={})
    assert s.db.backend == "duckdb"
    assert s.data.profile == "small"
    assert s.data.active.customers == 5000
    assert s.thresholds.large_cash_vnd == 400_000_000


def test_nested_env_override_is_yaml_typed() -> None:
    s = load_settings(environ={"AML__THRESHOLDS__LARGE_CASH_VND": "300000000"})
    assert s.thresholds.large_cash_vnd == 300_000_000


def test_db_backend_shortcut() -> None:
    s = load_settings(environ={"DB_BACKEND": "ORACLE"})
    assert s.db.backend == "oracle"


def test_profile_switch_changes_active_profile() -> None:
    s = load_settings(environ={"AML__DATA__PROFILE": "dense"})
    assert s.data.active.counterparties == (50, 100)


def test_unrelated_env_vars_ignored() -> None:
    raw = apply_env_overrides({"seed": 1}, {"PATH": "x", "AML_NOT_PREFIXED": "y"})
    assert raw == {"seed": 1}
