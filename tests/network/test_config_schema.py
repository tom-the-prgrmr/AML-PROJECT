"""AC1 for specs/network-detections.md: config, dependencies, NETWORK_RULES, DDL 130."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from aml.common.config import load_settings
from aml.common.db import SQL_ROOT, DuckDb, sql_file
from aml.dba.schema import SCHEMA_SCRIPTS, apply_schema

from .helpers import RULE_IDS, count, mod

DDL = "ddl/130_network.sql"
FEATURE_TABLE_COLUMNS = (
    "run_id, account_id, in_degree, out_degree, in_vnd, out_vnd, pagerank, pagerank_ratio, "
    "cycle_alerts, shared_cluster_id, shared_cluster_size, is_hub"
)


def test_ac1_default_network_config() -> None:
    n = load_settings(environ={}).network
    assert n.shared_attributes.min_customers == 5
    assert n.shared_attributes.max_customers_per_value == 50
    c = n.cycles
    assert (c.min_length, c.max_length, c.window_hours) == (3, 5, 168)
    assert (c.min_amount_vnd, c.min_amount_ratio, c.max_search_steps) == (
        50_000_000,
        0.7,
        1_000_000,
    )
    h = n.hubs
    assert (h.lookback_days, h.min_in_degree, h.min_pagerank_ratio) == (365, 10, 1.8)
    assert (h.min_inflow_vnd, h.pagerank_alpha) == (100_000_000, 0.85)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("CYCLES__MAX_LENGTH", "2", "max_length must be >= min_length"),
        ("CYCLES__MAX_LENGTH", "7", "max_length must be <= 6"),
        ("CYCLES__MIN_AMOUNT_RATIO", "1.5", "min_amount_ratio must be in [0, 1]"),
        ("SHARED_ATTRIBUTES__MIN_CUSTOMERS", "1", "min_customers must be >= 2"),
    ],
)
def test_ac1_invalid_network_config_is_rejected(key: str, value: str, message: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(message)):
        load_settings(environ={f"AML__NETWORK__{key}": value})


def test_ac1_networkx_and_scipy_are_installed() -> None:
    import networkx
    import scipy

    assert networkx.__version__.startswith("3.")
    assert scipy.__version__


def test_ac1_network_rules_registry() -> None:
    rules = mod("aml.graph.network.rules").NETWORK_RULES
    assert [r.rule_id for r in rules] == list(RULE_IDS)
    assert [r.rule_version for r in rules] == ["v1", "v1", "v1"]
    assert [r.target_typology for r in rules] == ["mule_ring", "round_tripping", "mule_ring"]
    assert all(r.description for r in rules)


def test_ac1_network_rule_params() -> None:
    rules = mod("aml.graph.network.rules")
    settings = load_settings(environ={})
    assert rules.network_rule_params("NET_SHARED_ATTRIBUTE", settings) == {
        "max_customers_per_value": 50,
        "min_customers": 5,
    }
    assert rules.network_rule_params("NET_CYCLE", settings) == {
        "max_length": 5,
        "max_search_steps": 1000000,
        "min_amount_ratio": 0.7,
        "min_amount_vnd": 50000000,
        "min_length": 3,
        "window_hours": 168,
    }
    assert rules.network_rule_params("NET_HUB", settings) == {
        "lookback_days": 365,
        "min_in_degree": 10,
        "min_inflow_vnd": 100000000,
        "min_pagerank_ratio": 1.8,
        "pagerank_alpha": 0.85,
    }


def test_ac1_ddl_130_is_registered_for_both_backends() -> None:
    duckdb = SCHEMA_SCRIPTS["duckdb"]
    assert DDL in duckdb
    assert duckdb.index(DDL) > duckdb.index("ddl/110_monitoring.sql")
    assert duckdb.index(DDL) < duckdb.index("ddl/050_customers_masked.sql")
    oracle = SCHEMA_SCRIPTS["oracle"]
    assert DDL in oracle
    assert oracle.index(DDL) > oracle.index("ddl/110_monitoring.sql")
    assert oracle.index(DDL) > oracle.index("ddl/120_property_graph.sql")
    assert oracle.index(DDL) < oracle.index("ddl/050_security_objects.sql")
    for backend in ("duckdb", "oracle"):
        assert sql_file(DDL, backend) == SQL_ROOT / backend / "ddl" / "130_network.sql"
        assert sql_file(DDL, backend).exists()


def test_ac1_apply_schema_twice_creates_empty_feature_table_and_view(duck: DuckDb) -> None:
    apply_schema(duck)
    apply_schema(duck)  # idempotent
    assert count(duck, "nx_account_features") == 0
    assert count(duck, "nx_account_features_current") == 0
    # the columns of the spec exist on the table (and the view exposes them too)
    duck.query_df(f"SELECT {FEATURE_TABLE_COLUMNS} FROM nx_account_features")
    duck.query_df(f"SELECT {FEATURE_TABLE_COLUMNS} FROM nx_account_features_current")
