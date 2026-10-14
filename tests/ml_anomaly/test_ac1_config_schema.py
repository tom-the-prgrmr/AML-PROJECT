"""AC1 for specs/ml-anomaly.md: config, DDL 200, SQL files, constants of the pure modules."""

from __future__ import annotations

import re

import pydantic
import pytest

from aml.common.config import load_settings
from aml.common.db import DuckDb, split_oracle_script, sql_file
from aml.dba.schema import SCHEMA_SCRIPTS, apply_schema

from .helpers import case_features, features, query, scalar

DDL = "ddl/200_ml_anomaly.sql"
LEGS = "ml/anomaly_legs.sql"
TABLES = ("anomaly_runs", "anomaly_scores", "anomaly_scores_current", "case_anomaly_features")
MESSAGES = [
    ("BASELINE_DAYS", "0", "ml.anomaly baseline_days must be >= 1"),
    (
        "MIN_BASELINE_DAYS",
        "91",
        "ml.anomaly min_baseline_days must be between 0 and baseline_days",
    ),
    (
        "NIGHT_END_HOUR",
        "22",
        "ml.anomaly night_start_hour and night_end_hour must be 0..23 and differ",
    ),
    (
        "NIGHT_START_HOUR",
        "24",
        "ml.anomaly night_start_hour and night_end_hour must be 0..23 and differ",
    ),
    ("N_ESTIMATORS", "5", "ml.anomaly n_estimators must be between 10 and 2000"),
    ("MAX_SAMPLES", "1", "ml.anomaly max_samples must be >= 2"),
    ("ALERT_TOP_FRACTION", "0", "ml.anomaly alert_top_fraction must be in (0, 0.1]"),
    ("ALERT_TOP_FRACTION", "0.2", "ml.anomaly alert_top_fraction must be in (0, 0.1]"),
    ("MIN_SAMPLES", "1", "ml.anomaly min_samples must be >= 2"),
    ("TOP_DEVIATIONS", "15", "ml.anomaly top_deviations must be between 1 and 14"),
]


def test_ac1_default_config() -> None:
    cfg = load_settings(environ={}).ml.anomaly
    assert cfg.baseline_days == 90
    assert cfg.min_baseline_days == 28
    assert (cfg.night_start_hour, cfg.night_end_hour) == (22, 6)
    assert cfg.n_estimators == 200
    assert cfg.max_samples == 256
    assert cfg.alert_top_fraction == 0.005
    assert cfg.min_samples == 50
    assert cfg.top_deviations == 3
    assert cfg.features == "auto"
    assert cfg.results_dir == "results/phase7b"


def test_ac1_features_off_is_a_string() -> None:
    # YAML reads a bare `off` as False: the config must still give the string
    assert load_settings(environ={"AML__ML__ANOMALY__FEATURES": "off"}).ml.anomaly.features == "off"


def test_ac1_features_on_is_rejected() -> None:
    with pytest.raises(pydantic.ValidationError):
        load_settings(environ={"AML__ML__ANOMALY__FEATURES": "on"})


@pytest.mark.parametrize(("name", "value", "message"), MESSAGES)
def test_ac1_bad_values_raise_their_message(name: str, value: str, message: str) -> None:
    with pytest.raises(pydantic.ValidationError, match=re.escape(message)):
        load_settings(environ={f"AML__ML__ANOMALY__{name}": value})


def test_ac1_ddl_200_is_listed_after_190_and_before_the_security_scripts() -> None:
    for backend in ("duckdb", "oracle"):
        scripts = list(SCHEMA_SCRIPTS[backend])
        at = scripts.index(DDL)
        assert scripts.index("ddl/190_memo_analysis.sql") + 1 == at, backend
        security = [i for i, s in enumerate(scripts) if s.startswith("ddl/050_")]
        assert security and all(at < i for i in security), backend


def test_ac1_apply_schema_twice_creates_empty_objects(duck: DuckDb) -> None:
    apply_schema(duck)
    apply_schema(duck)
    for name in TABLES:
        assert scalar(duck, f"SELECT COUNT(*) FROM {name}") == 0, name
    columns = set(
        query(
            duck,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'anomaly_scores'",
        )["column_name"]
    )
    assert {"run_id", "cif", "month", "model_version", "score", "rank", "alerted"} <= columns
    assert {"top_deviations", "window_start", "window_end"} <= columns


def test_ac1_sql_files_resolve_per_backend() -> None:
    root = sql_file(LEGS, "duckdb").parents[2]
    assert sql_file(LEGS, "duckdb") == root / "duckdb" / "ml" / "anomaly_legs.sql"
    assert sql_file(LEGS, "oracle") == root / "oracle" / "ml" / "anomaly_legs.sql"
    for backend in ("duckdb", "oracle"):
        assert sql_file(DDL, backend).exists()


def test_ac1_oracle_scripts_split_into_the_expected_statements() -> None:
    legs = split_oracle_script(sql_file(LEGS, "oracle").read_text(encoding="utf-8"))
    assert len(legs) == 1
    ddl = split_oracle_script(sql_file(DDL, "oracle").read_text(encoding="utf-8"))
    assert len(ddl) >= 4
    assert any("MODIFY" in s and "feature_version" in s for s in ddl)


def test_ac1_module_constants() -> None:
    f = features()
    assert f.ANOMALY_VERSION == "anomaly/v1"
    assert len(f.ANOMALY_FEATURES) == 14
    assert f.ANOMALY_FEATURES[-4:] == f.GRAPH_FEATURES
    assert set(f.FEATURE_DOCS) == set(f.ANOMALY_FEATURES)
    assert all(isinstance(d, str) and d.strip() for d in f.FEATURE_DOCS.values())
    assert case_features().ANOMALY_CASE_FEATURES == ("anomaly_max_score", "anomaly_flagged_months")
    assert case_features().NON_NEGATIVE_ANOMALY == case_features().ANOMALY_CASE_FEATURES
    assert case_features().ANOMALY_FEATURE_TAG == "+anom/v1"
