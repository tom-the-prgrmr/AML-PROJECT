"""AC1 for specs/screening-ml.md: config, DDL 210, SQL resolution, constants."""

from __future__ import annotations

import inspect

import pydantic
import pytest

from aml.common.config import load_settings
from aml.common.db import DuckDb, split_oracle_script, sql_file
from aml.dba.schema import SCHEMA_SCRIPTS, apply_schema
from aml.screening.recording import config_hash

from .helpers import mod, query, scalar

DDL = "ddl/210_screening_ml.sql"
TABLES = (
    "screening_ml_labels",
    "screening_ml_features",
    "screening_ml_models",
    "screening_ml_model_active",
    "screening_ml_training",
    "screening_ml_scores",
    "screening_ml_scores_current",
)


def test_ac1_default_config() -> None:
    cfg = load_settings(environ={}).ml.screening
    assert cfg.simulate_fraction == 0.7
    assert cfg.simulated_actor == "simulated_analyst"
    assert cfg.use_human_reviews is True
    assert cfg.cv_folds == 5
    assert cfg.top_features == 3
    assert cfg.logreg.c == 1.0
    assert cfg.logreg.max_iter == 1000


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("SIMULATE_FRACTION", "0", r"simulate_fraction must be in \(0, 1\]"),
        ("SIMULATE_FRACTION", "1.5", r"simulate_fraction must be in \(0, 1\]"),
        ("CV_FOLDS", "1", "cv_folds must be >= 2"),
        ("SIMULATED_ACTOR", "system", "simulated_actor must differ from audit.system_actor"),
        ("LOGREG__C", "0", ""),
    ],
)
def test_ac1_invalid_config_is_rejected(key: str, value: str, message: str) -> None:
    with pytest.raises(pydantic.ValidationError, match=message or None):
        load_settings(environ={f"AML__ML__SCREENING__{key}": value})


def test_ac1_config_hash_of_screening_is_unchanged() -> None:
    changed = load_settings(environ={"AML__ML__SCREENING__CV_FOLDS": "3"})
    assert config_hash(changed) == config_hash(load_settings(environ={}))


@pytest.mark.parametrize("backend", ["duckdb", "oracle"])
def test_ac1_ddl_is_registered_in_order(backend: str) -> None:
    scripts = list(SCHEMA_SCRIPTS[backend])
    assert DDL in scripts
    assert scripts.index("ddl/190_memo_analysis.sql") < scripts.index(DDL)
    assert all(scripts.index(DDL) < i for i, s in enumerate(scripts) if "/050_" in s)
    assert sql_file(DDL, backend).parent.parent.name == backend


def test_ac1_oracle_script_is_terminated_with_slashes() -> None:
    text = sql_file(DDL, "oracle").read_text(encoding="utf-8")
    assert len(split_oracle_script(text)) == 7  # 5 tables and 2 views
    assert text.count("-955") == 5


def test_ac1_schema_applies_twice_and_tables_are_empty(duck: DuckDb) -> None:
    apply_schema(duck)
    apply_schema(duck)
    for table in TABLES:
        assert scalar(duck, f"SELECT COUNT(*) FROM {table}") == 0, table
    cols = set(query(duck, "SELECT * FROM screening_ml_scores").columns)
    assert not cols & {"decision", "status"}


def test_ac1_features_constant() -> None:
    features = mod("aml.screening.ml.features")
    assert len(features.FEATURES) == 19
    assert len(set(features.FEATURES)) == 19
    assert features.FEATURE_VERSION == "screening-ml-features/v1"
    assert "final_score" not in features.FEATURES
    assert "ground_truth" not in inspect.getsource(features)
