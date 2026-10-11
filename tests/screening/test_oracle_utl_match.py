"""AC4 for specs/screening-oracle-incremental.md: UTL_MATCH values and the SQL screen on Oracle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rapidfuzz.distance import JaroWinkler

from aml.common.config import load_settings, read_environ
from aml.common.db import DuckDb, OracleDb

from .helpers import mod
from .helpers_3b import AS_OF, TRUE_PAIRS

UTL = [
    ("HUU LONG TRA", "HUU LONG TRAN", 98),
    ("TRA", "TRAN", 94),
    ("AN", "ANH", 91),
    ("DO SON XUAN", "DO SON XUAN", 100),
    ("HA", "HOA", 64),
]


def _pairs(df: Any) -> set[tuple[str, str]]:
    return set(zip(df["cif"], df["entry_id"], strict=True))


@pytest.mark.oracle
def test_ac4_utl_match_values_and_sql_screen_on_oracle(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    load, runner = mod("aml.datagen.load"), mod("aml.screening.runner")
    sc = mod("aml.screening.sql_compare")
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle")})
    with OracleDb(osettings) as odb:
        for a, b, want in UTL:
            df = odb.query_df(
                "SELECT UTL_MATCH.JARO_WINKLER_SIMILARITY(:a, :b) AS s FROM dual",
                {"a": a, "b": b},
            )
            assert int(df.iloc[0, 0]) == want, (a, b)
        assert int(100 * JaroWinkler.similarity("HA", "HOA")) == 61

        load.load_parquet(odb, tiny_parquet)
        runner.run_screening(odb, osettings, as_of=AS_OF)
        sc.sync_screening_names(odb, osettings)
        ora = sc.sql_screen(odb, osettings)
        cmp = sc.compare_sql_python(odb, osettings)
        tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb"})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        load.load_parquet(ddb, tiny_parquet)
        runner.run_screening(ddb, dsettings, as_of=AS_OF)
        sc.sync_screening_names(ddb, dsettings)
        duck = sc.sql_screen(ddb, dsettings)

    assert len(ora) == 30
    assert len(duck) == 32
    assert _pairs(ora) <= _pairs(duck)
    assert _pairs(ora) >= TRUE_PAIRS
    assert _pairs(duck) >= TRUE_PAIRS

    assert cmp.backend == "oracle"
    assert cmp.function == "UTL_MATCH.JARO_WINKLER_SIMILARITY"
    assert (cmp.sql_pairs, cmp.both, cmp.python_only, cmp.sql_tp) == (30, 5, 0, 5)
    assert {
        "SCREENING_CUSTOMER_NAME",
        "SCREENING_LIST_NAME",
        "SCREENING_STATE",
        "SCREENING_TOKEN_STATS",
    } <= tables
