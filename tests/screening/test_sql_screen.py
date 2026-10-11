"""AC1-AC3 for specs/screening-oracle-incremental.md: SQL files, name tables, SQL screen."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from aml.common.config import load_settings
from aml.common.db import SQL_ROOT, DuckDb, split_oracle_script, sql_file

from .helpers import mod
from .helpers_3b import TRUE_PAIRS
from .helpers_3c import audit_count, count, duck_settings, full_screen_tiny, load_tiny_duck, query

ROOT = Path(__file__).resolve().parents[2]
DDL = "ddl/090_screening_state.sql"
JW = "screening/jw_screen.sql"


def test_ac1_config_ddl_sql_files_and_docs() -> None:
    assert load_settings(environ={}).screening.sql_length_band == 3
    scripts = mod("aml.dba.schema").SCHEMA_SCRIPTS
    for backend in ("duckdb", "oracle"):
        assert DDL in scripts[backend]
        assert sql_file(DDL, backend) == SQL_ROOT / backend / DDL
        assert sql_file(JW, backend) == SQL_ROOT / backend / JW
    assert scripts["oracle"].index(DDL) < scripts["oracle"].index("ddl/050_security_objects.sql")

    ora = sql_file(JW, "oracle").read_text(encoding="utf-8")
    duck = sql_file(JW, "duckdb").read_text(encoding="utf-8")
    assert "UTL_MATCH.JARO_WINKLER_SIMILARITY" in ora
    assert "jaro_winkler_similarity" in duck
    stmts = split_oracle_script(ora)
    assert len(stmts) == 1
    assert stmts[0].lstrip().upper().startswith(("SELECT", "WITH"))
    for text in (ora, duck):
        assert "{threshold}" in text and "{length_band}" in text
        assert set(re.findall(r"\{([^{}]*)\}", text)) == {"threshold", "length_band"}

    docs = (ROOT / "docs" / "screening.md").read_text(encoding="utf-8")
    assert "Oracle UTL_MATCH vs Python" in docs
    assert "Incremental screening" in docs


@pytest.fixture
def tiny(tiny_parquet: Path, tmp_path: Path) -> Iterator[DuckDb]:
    db = load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb")
    yield db
    db.close()


def test_ac2_sync_names_counts_and_idempotent(tiny: DuckDb) -> None:
    sync = mod("aml.screening.sql_compare").sync_screening_names
    settings = duck_settings()
    expected = {"screening_customer_name": 300, "screening_list_name": 445}
    assert sync(tiny, settings) == expected
    assert sync(tiny, settings) == expected
    assert count(tiny, "SELECT COUNT(*) FROM screening_customer_name") == 300
    assert count(tiny, "SELECT COUNT(*) FROM screening_list_name") == 445

    c = query(tiny, "SELECT * FROM screening_customer_name WHERE cif = 'CIF00000104'")
    assert len(c) == 1
    assert (c.iloc[0]["name_norm"], c.iloc[0]["name_key"]) == ("HUYNH XUAN SON", "HUYNH SON XUAN")

    w = query(tiny, "SELECT * FROM screening_list_name WHERE entry_id = 'WL000084'")
    got = {(r.name_type, r.name_norm, r.name_key) for r in w.itertuples()}
    assert len(w) == 3
    assert {(t, n) for t, n, _ in got} == {
        ("PRIMARY", "NGUYEN ANH LONG"),
        ("AKA", "DANG ANH ANH"),
        ("REORDERED", "LONG NGUYEN ANH"),
    }
    assert [k for t, _, k in got if t == "AKA"] == ["ANH ANH DANG"]


def test_ac3_sql_screen_and_comparison_on_duckdb(tiny_parquet: Path, tmp_path: Path) -> None:
    db, settings = full_screen_tiny(tiny_parquet, tmp_path / "tiny.duckdb")
    mc = mod("aml.screening.sql_compare")
    mc.sync_screening_names(db, settings)
    df = mc.sql_screen(db, settings)
    assert list(df.columns) == ["cif", "entry_id", "jw_score"]
    assert len(df) == 32
    pairs = list(zip(df["cif"], df["entry_id"], strict=True))
    assert len(set(pairs)) == 32
    scores = [int(s) for s in df["jw_score"]]
    assert all(90 <= s <= 100 for s in scores)
    assert all(float(s) == float(int(s)) for s in df["jw_score"])
    truth = df[[p in TRUE_PAIRS for p in pairs]]
    assert len(truth) == 5
    assert set(int(s) for s in truth["jw_score"]) == {100}

    audit_before = audit_count(db)
    cmp = mc.compare_sql_python(db, settings)
    assert cmp.backend == "duckdb"
    assert cmp.function == "jaro_winkler_similarity" == mc.SQL_FUNCTIONS["duckdb"]
    assert cmp.threshold == 90
    assert (cmp.sql_pairs, cmp.python_pairs) == (32, 5)
    assert (cmp.both, cmp.sql_only, cmp.python_only) == (5, 27, 0)
    assert (cmp.truth, cmp.sql_tp, cmp.python_tp) == (5, 5, 5)
    assert cmp.sql_seconds >= 0

    assert audit_count(db) == audit_before + 1
    rows = query(
        db,
        "SELECT decision, entity_id, details FROM audit_log WHERE module = 'screening' "
        "AND entity_type = 'screening_compare'",
    )
    assert len(rows) == 1
    assert rows.iloc[0]["decision"] == "COMPARISON_CAPTURED"
    assert rows.iloc[0]["entity_id"] == "duckdb"
    from tests.dba.conftest import audit_rows

    d = audit_rows(db, "module = 'screening' AND entity_type = 'screening_compare'")
    assert d.iloc[0]["details"]["sql_pairs"] == 32
    db.close()


def test_ac3_compare_before_any_run_raises(tiny: DuckDb) -> None:
    mc = mod("aml.screening.sql_compare")
    with pytest.raises(mod("aml.screening.runner").ScreeningError, match="run `aml screen` first"):
        mc.compare_sql_python(tiny, duck_settings())
