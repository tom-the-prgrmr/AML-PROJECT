"""AC1 for specs/ml-governance.md: config, DDL 220 and the four below-the-line tables."""

from __future__ import annotations

import re

import pydantic
import pytest

from aml.common.config import load_settings
from aml.common.db import DuckDb, split_oracle_script, sql_file
from aml.dba.schema import SCHEMA_SCRIPTS, apply_schema

from .helpers import query, scalar

DDL = "ddl/220_ml_governance.sql"
TABLES = ("btl_samples", "btl_members", "btl_features", "btl_evaluations")
MODELS = ["prioritization", "memo_classifier", "anomaly", "screening_match"]
SAMPLE = "AML__CASES__PRIORITIZATION__BELOW_THE_LINE__SAMPLE_SIZE"


def test_ac1_default_config() -> None:
    s = load_settings(environ={})
    below = s.cases.prioritization.below_the_line
    assert below.enabled is False
    assert below.sample_size == 200
    assert s.ml.governance.cards_dir == "docs/models"
    assert s.ml.governance.models == MODELS


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({SAMPLE: "0"}, "below_the_line sample_size must be >= 1"),
        ({"AML__ML__GOVERNANCE__MODELS": "[foo]"}, "unknown model card 'foo'"),
        (
            {"AML__ML__GOVERNANCE__MODELS": "[memo_classifier, memo_classifier]"},
            "governance models must not repeat",
        ),
    ],
)
def test_ac1_invalid_config_is_rejected(env: dict[str, str], message: str) -> None:
    with pytest.raises(pydantic.ValidationError) as caught:
        load_settings(environ=env)
    assert message in str(caught.value)


@pytest.mark.parametrize("backend", ["duckdb", "oracle"])
def test_ac1_ddl_is_registered_in_order(backend: str) -> None:
    scripts = list(SCHEMA_SCRIPTS[backend])
    at = scripts.index(DDL)
    assert at > scripts.index("ddl/190_memo_analysis.sql")
    for earlier in (s for s in scripts if s.startswith(("ddl/200_", "ddl/210_"))):
        assert at > scripts.index(earlier)
    for later in (s for s in scripts if s.startswith("ddl/050_")):
        assert at < scripts.index(later)
    assert sql_file(DDL, backend).is_file()


def test_ac1_oracle_ddl_statements_end_with_a_slash_line() -> None:
    text = sql_file(DDL, "oracle").read_text(encoding="utf-8")
    statements = split_oracle_script(text)
    slashes = [ln for ln in text.splitlines() if ln.strip() == "/"]
    assert len(statements) == len(slashes) == 4
    assert text.rstrip().splitlines()[-1].strip() == "/"
    for statement in statements:
        assert "EXECUTE IMMEDIATE" in statement
        assert "-955" in statement  # ORA-00955 is swallowed: the DDL is idempotent


def test_ac1_apply_schema_twice_and_empty_tables(duck: DuckDb) -> None:
    apply_schema(duck)
    apply_schema(duck)
    for table in TABLES:
        assert int(scalar(duck, f"SELECT COUNT(*) FROM {table}")) == 0
    columns = query(
        duck,
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'btl_members'",
    )["column_name"]
    assert set(columns) == {"sample_id", "golden_customer_id", "label", "typologies", "reason"}
    assert not [c for c in columns if re.search("disposition|status", c)]
