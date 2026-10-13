"""AC1 for specs/case-prioritization.md: config, dependencies, DDL 180, feature names."""

from __future__ import annotations

import importlib
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from aml.common.config import load_settings
from aml.common.db import SQL_ROOT, DuckDb, sql_file
from aml.dba.schema import SCHEMA_SCRIPTS, apply_schema

from .helpers import count, query
from .prio_helpers import EXPECTED_FEATURES, features_mod

DDL = "ddl/180_case_prioritization.sql"
PREFIX = "AML__CASES__PRIORITIZATION__"
OBJECTS = (
    "case_features",
    "case_models",
    "case_scores",
    "case_model_active",
    "case_scores_current",
    "case_queue",
)
ROOT = Path(__file__).resolve().parents[2]


def test_ac1_default_prioritization_config() -> None:
    p = load_settings(environ={}).cases.prioritization
    assert p.model == "logreg"
    assert p.simulate_dispositions is True
    assert p.simulate_fraction == 0.7
    assert p.simulated_actor == "simulated_analyst"
    assert p.cv_folds == 5
    assert p.top_features == 5
    assert p.top_fractions == [0.1, 0.2, 0.5]
    assert p.logreg.c == 1.0
    assert p.logreg.max_iter == 1000


# (key, a valid value and what it parses to, an invalid value, expected message or None)
CASES: list[tuple[str, str, Any, str, str | None]] = [
    ("MODEL", "lightgbm", "lightgbm", "xgboost", None),
    ("SIMULATE_FRACTION", "1.0", 1.0, "0", "simulate_fraction must be in (0, 1]"),
    ("SIMULATE_FRACTION", "0.25", 0.25, "1.5", "simulate_fraction must be in (0, 1]"),
    ("CV_FOLDS", "3", 3, "1", "cv_folds must be >= 2"),
    (
        "SIMULATED_ACTOR",
        "demo_bot",
        "demo_bot",
        "system",
        "simulated_actor must differ from audit.system_actor",
    ),
    ("TOP_FEATURES", "3", 3, "0", None),
    ("TOP_FRACTIONS", "[0.25]", [0.25], "[0, 0.5]", None),
]


@pytest.mark.parametrize(("key", "good", "parsed", "bad", "message"), CASES)
def test_ac1_overrides_are_validated(
    key: str, good: str, parsed: Any, bad: str, message: str | None
) -> None:
    p = load_settings(environ={PREFIX + key: good}).cases.prioritization
    assert getattr(p, key.lower()) == parsed
    with pytest.raises(ValidationError) as exc:
        load_settings(environ={PREFIX + key: bad})
    if message:
        assert message in str(exc.value)


def test_ac1_dependencies_in_pyproject() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    def names(deps: list[str]) -> set[str]:
        return {re.split(r"[<>=!~ \[;]", d, maxsplit=1)[0].lower() for d in deps}

    assert "scikit-learn" in names(project["dependencies"])
    assert "lightgbm" not in names(project["dependencies"])
    assert "lightgbm" in names(project["optional-dependencies"]["ml"])


def test_ac1_scikit_learn_is_importable() -> None:
    assert importlib.import_module("sklearn").__version__


def test_ac1_ddl_180_is_registered_for_both_backends() -> None:
    for backend in ("duckdb", "oracle"):
        scripts = SCHEMA_SCRIPTS[backend]
        assert DDL in scripts, backend
        assert scripts.index(DDL) > scripts.index("ddl/170_case_suppression.sql")
        late = [i for i, s in enumerate(scripts) if s.startswith("ddl/050_")]
        assert late and scripts.index(DDL) < min(late)
        assert sql_file(DDL, backend) == SQL_ROOT / backend / "ddl" / "180_case_prioritization.sql"
        assert sql_file(DDL, backend).exists()


def test_ac1_apply_schema_twice_creates_empty_tables_and_views(duck: DuckDb) -> None:
    apply_schema(duck)
    apply_schema(duck)  # idempotent
    for name in OBJECTS:
        assert count(duck, name) == 0, name


def test_ac1_case_scores_has_no_disposition_or_status_column(duck: DuckDb) -> None:
    apply_schema(duck)
    columns = set(query(duck, "SELECT * FROM case_scores WHERE 1 = 0").columns)
    assert not {c for c in columns if "disposition" in c or "status" in c}
    assert {
        "score_run_id",
        "run_id",
        "case_id",
        "model_id",
        "model_version",
        "score",
        "queue_rank",
        "top_features",
        "scored_ts",
    } <= columns
    models = set(query(duck, "SELECT * FROM case_models WHERE 1 = 0").columns)
    assert {
        "model_id",
        "kind",
        "version",
        "feature_version",
        "trained_ts",
        "as_of",
        "seed",
        "cases",
        "suspicious",
        "false_positive",
        "features",
        "params",
        "metrics",
        "artifact",
        "data_hash",
        "actor",
    } <= models
    features = set(query(duck, "SELECT * FROM case_features WHERE 1 = 0").columns)
    assert {"run_id", "case_id", "feature", "value"} <= features


def test_ac1_feature_names_and_version() -> None:
    m = features_mod()
    assert len(m.FEATURES) == 35
    assert len(set(m.FEATURES)) == 35
    assert tuple(m.FEATURES) == EXPECTED_FEATURES
    assert m.FEATURE_VERSION == "features/v1"
