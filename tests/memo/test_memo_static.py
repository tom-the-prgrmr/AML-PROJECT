"""AC1 for specs/memo-analysis.md: config, DDL, SQL files, constants and import boundaries."""

from __future__ import annotations

import pkgutil
import re
import subprocess
import sys
from pathlib import Path

import pydantic
import pytest

from aml.common.config import load_settings
from aml.common.db import DuckDb, split_oracle_script, sql_file
from tests.cases.helpers import count, mod, query

from .helpers import classify_mod, features_mod, normalize_mod

OBJECTS = (
    "memo_runs",
    "memo_classifications",
    "memo_classifications_current",
    "memo_overrides",
    "memo_overrides_current",
    "memo_labels_current",
    "case_memo_features",
)
MODULES = ("normalize", "classify", "runner", "features", "compare", "evaluate", "relabel")
CATEGORIES = (
    "salary",
    "loan_repayment",
    "gambling_like",
    "crypto_like",
    "suspicious_wording",
    "other",
)


def test_ac1_memo_config_defaults_and_validation() -> None:
    memo = load_settings(environ={}).memo
    assert memo.max_chars == 200
    assert memo.max_retries == 1
    assert memo.max_llm_keys == 500
    assert memo.features == "auto"
    assert memo.results_dir == "results/phase8"
    with pytest.raises(pydantic.ValidationError):
        load_settings(environ={"AML__MEMO__FEATURES": "on"})
    for name, value, message in (
        ("MAX_CHARS", "19", "memo max_chars must be >= 20"),
        ("MAX_RETRIES", "4", "memo max_retries must be between 0 and 3"),
        ("MAX_LLM_KEYS", "0", "memo max_llm_keys must be >= 1"),
    ):
        with pytest.raises(pydantic.ValidationError, match=re.escape(message)):
            load_settings(environ={f"AML__MEMO__{name}": value})


def test_ac1_ddl_190_is_listed_and_applies_twice(duck: DuckDb) -> None:
    schema = mod("aml.dba.schema")
    for backend in ("duckdb", "oracle"):
        scripts = list(schema.SCHEMA_SCRIPTS[backend])
        at = scripts.index("ddl/190_memo_analysis.sql")
        assert scripts.index("ddl/180_case_prioritization.sql") < at
        security = [i for i, s in enumerate(scripts) if s.startswith("ddl/050_")]
        assert security and all(at < i for i in security)
    schema.apply_schema(duck)
    schema.apply_schema(duck)
    for name in OBJECTS:
        assert count(duck, name) == 0, name
    columns = set(
        query(
            duck,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'memo_classifications'",
        )["column_name"]
    )
    assert not columns & {"disposition", "status", "raw_output"}
    assert {"memo_key", "memo_norm", "category", "method", "attempts", "pattern"} <= columns


def test_ac1_sql_files_resolve_per_backend() -> None:
    for name in ("memo/distinct_memos.sql", "memo/case_memos.sql"):
        for backend in ("duckdb", "oracle"):
            path = sql_file(name, backend)
            assert path.parent.parent.name == backend, path
        oracle = sql_file(name, "oracle").read_text(encoding="utf-8")
        assert len(split_oracle_script(oracle)) == 1


def test_ac1_constants() -> None:
    norm, cls, feats = normalize_mod(), classify_mod(), features_mod()
    cases = mod("aml.cases.features")
    assert norm.MEMO_VERSION == "memo/v1"
    assert cls.CATEGORIES == CATEGORIES
    schema = cls.MEMO_SCHEMA
    assert schema["properties"]["category"]["enum"] == list(CATEGORIES)
    assert schema["required"] == ["category"]
    assert schema["additionalProperties"] is False
    assert list(schema["properties"]) == ["category"]
    assert len(feats.MEMO_FEATURES) == 6
    assert not set(feats.MEMO_FEATURES) & set(cases.FEATURES)
    assert set(feats.NON_NEGATIVE) < set(feats.MEMO_FEATURES)
    assert feats.MEMO_FEATURE_VERSION == "features/v1+memo/v1"
    assert len(feats.MEMO_FEATURE_VERSION) <= 20
    assert len(cases.FEATURES) == 35  # 7c is unchanged
    assert cases.FEATURE_VERSION == "features/v1"


def test_ac1_memo_modules_import_without_the_assistant_package() -> None:
    """AC1: with `aml.assistant` blocked, every `aml.memo` module still imports.

    Run in a child interpreter so the blocked entry cannot leak into other tests.
    """
    names = [f"aml.memo.{m}" for m in MODULES]
    code = (
        "import sys, importlib\n"
        "sys.modules['aml.assistant'] = None\n"
        f"for name in {names!r}:\n"
        "    importlib.import_module(name)\n"
        "assert not any(m.startswith('aml.assistant.') for m in sys.modules)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr


def test_ac1_memo_sources_stay_inside_their_lane() -> None:
    """AC1: no graph driver, no truth labels, no decisions, no dynamic code in `aml.memo`.

    `eval(` / `exec(` are checked as calls of the builtins: the spec's own `run_memo_eval(` is a
    function name, not a call of `eval`.
    """
    package = mod("aml.memo")
    banned = ("neo4j", "ground_truth", "record_disposition", "record_run", "good_guy")
    dynamic = re.compile(r"(?<![\w.])(eval|exec)\(")
    seen = set()
    for info in pkgutil.iter_modules(package.__path__):
        source = (Path(package.__path__[0]) / f"{info.name}.py").read_text(encoding="utf-8")
        seen.add(info.name)
        for word in banned:
            assert word not in source, f"{info.name}: {word}"
        assert not dynamic.search(source), info.name
    assert set(MODULES) <= seen


def test_ac1_review_max_chars_has_an_upper_bound() -> None:
    """AC1 (review fix): a normalised memo must fit memo_classifications.memo_norm."""
    assert load_settings(environ={"AML__MEMO__MAX_CHARS": "1000"}).memo.max_chars == 1000
    with pytest.raises(pydantic.ValidationError, match=re.escape("memo max_chars must be <= 1000")):
        load_settings(environ={"AML__MEMO__MAX_CHARS": "1001"})


def test_ac12_review_memo_list_drops_control_characters() -> None:
    """AC12 (review fix): `aml memo list` prints memo text without terminal control sequences."""
    printable = mod("aml.memo.cli").printable
    assert printable("nap \x1b[31mtien\x1b[0m\u200b ok") == "nap [31mtien[0m ok"
    assert printable("trả nợ vay bạn bè") == "trả nợ vay bạn bè"
