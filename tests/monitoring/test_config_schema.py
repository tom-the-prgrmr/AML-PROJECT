"""AC1 for specs/monitoring-rules.md: config, RULES, rule files, DDL 110 and rule_params."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from aml.common.config import load_settings
from aml.common.db import SQL_ROOT, DuckDb, split_oracle_script, sql_file

from .helpers import RULE_IDS, mod


def _statements(path_text: str, backend: str) -> list[str]:
    if backend == "oracle":
        return split_oracle_script(path_text)
    parts = [p.strip() for p in path_text.split(";")]
    return [
        p
        for p in parts
        if p and not all(ln.strip().startswith("--") or not ln.strip() for ln in p.splitlines())
    ]


def _without_comments(statement: str) -> str:
    return "\n".join(ln for ln in statement.splitlines() if not ln.strip().startswith("--")).strip()


def test_ac1_default_monitoring_config() -> None:
    m = load_settings(environ={}).monitoring
    assert m.known_counterparty_days == 14
    assert (m.structuring.window_days, m.structuring.min_deposits) == (14, 3)
    rapid = m.rapid_movement
    assert (rapid.window_hours, rapid.min_inflow_vnd, rapid.min_pass_through_pct) == (
        24,
        200_000_000,
        0.9,
    )
    vel = m.high_velocity
    assert (vel.window_hours, vel.min_txns, vel.min_total_vnd) == (24, 8, 100_000_000)
    fan = m.fan_in_out
    assert (fan.window_days, fan.min_counterparties, fan.min_total_vnd) == (7, 8, 100_000_000)
    dor = m.dormant_reactivation
    assert (dor.dormant_days, dor.window_hours, dor.min_amount_vnd) == (90, 24, 100_000_000)


def test_ac1_invalid_config_is_rejected() -> None:
    with pytest.raises(ValidationError, match=re.escape("min_pass_through_pct must be in (0, 1]")):
        load_settings(environ={"AML__MONITORING__RAPID_MOVEMENT__MIN_PASS_THROUGH_PCT": "1.5"})
    with pytest.raises(ValidationError, match=re.escape("known_counterparty_days must be >= 1")):
        load_settings(environ={"AML__MONITORING__KNOWN_COUNTERPARTY_DAYS": "0"})


def test_ac1_rules_catalogue() -> None:
    rules = mod("aml.monitoring.rules").RULES
    assert [r.rule_id for r in rules] == list(RULE_IDS)
    assert all(r.rule_version == "v1" for r in rules)
    assert [r.target_typology for r in rules] == [
        "structuring",
        "rapid_movement",
        None,
        "mule_ring",
        "mule_ring",
        None,
    ]
    assert len({r.sql_file for r in rules}) == 5
    by_id = {r.rule_id: r for r in rules}
    assert by_id["FAN_IN"].sql_file == by_id["FAN_OUT"].sql_file == "monitoring/fan_in_out.sql"


@pytest.mark.parametrize("backend", ["duckdb", "oracle"])
def test_ac1_rule_files_are_single_with_statements_with_known_placeholders(backend: str) -> None:
    rules_mod = mod("aml.monitoring.rules")
    settings = load_settings(environ={})
    for rule in rules_mod.RULES:
        path = sql_file(rule.sql_file, backend)
        assert path == SQL_ROOT / backend / "monitoring" / path.name, rule.rule_id
        text = path.read_text(encoding="utf-8")
        statements = _statements(text, backend)
        assert len(statements) == 1, (backend, rule.rule_id, len(statements))
        assert _without_comments(statements[0]).upper().startswith("WITH"), rule.rule_id
        placeholders = set(re.findall(r"\{(\w+)\}", text))
        allowed = set(rules_mod.rule_params(rule.rule_id, settings)) | {"cutoff"}
        assert placeholders <= allowed, (backend, rule.rule_id, placeholders - allowed)


def test_ac1_rule_params() -> None:
    rule_params = mod("aml.monitoring.rules").rule_params
    settings = load_settings(environ={})
    assert rule_params("STRUCTURING", settings) == {
        "band_low_vnd": 360000000,
        "large_cash_vnd": 400000000,
        "min_deposits": 3,
        "window_days": 14,
    }
    assert rule_params("FAN_OUT", settings) == {
        "direction": "OUT",
        "known_counterparty_days": 14,
        "min_counterparties": 8,
        "min_total_vnd": 100000000,
        "window_days": 7,
    }


def test_ac1_ddl_110_is_registered_in_both_backends() -> None:
    scripts = mod("aml.dba.schema").SCHEMA_SCRIPTS
    for backend, last in (
        ("duckdb", "ddl/050_customers_masked.sql"),
        ("oracle", "ddl/050_security_objects.sql"),
    ):
        order = list(scripts[backend])
        assert "ddl/110_monitoring.sql" in order, backend
        assert order.index("ddl/100_entity_resolution.sql") < order.index("ddl/110_monitoring.sql")
        assert order.index("ddl/110_monitoring.sql") < order.index(last)


def test_ac1_apply_schema_twice_creates_empty_objects(duck: DuckDb) -> None:
    schema = mod("aml.dba.schema")
    schema.apply_schema(duck)
    schema.apply_schema(duck)
    for name in (
        "monitoring_runs",
        "alerts",
        "alert_accounts",
        "alert_evidence",
        "alerts_current",
        "txn_legs",
    ):
        assert duck.query_df(f"SELECT COUNT(*) FROM {name}").iloc[0, 0] == 0, name
