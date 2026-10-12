"""AC4 (Oracle part) for specs/neo4j-queries.md: neo4j == cte_raw == pgq on Oracle.

Needs Oracle, Neo4j, ORACLE_SYS_PASSWORD and ORACLE_DEMO_PASSWORD. Like the 6a Oracle test it
reloads TINY into the schema owner and re-applies the grants.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import DuckDb, OracleDb
from tests.graph.helpers import HUB, MULE, PAYROLL, RND
from tests.neo4j_sync.helpers import TINY_S11, s11

from .conftest import Neo
from .helpers import mod, neo_settings, run_sync, trace

pytestmark = [pytest.mark.oracle, pytest.mark.neo4j]

# (account, hops, hours, expected rows)
CASES = [
    (RND, 4, 168, 4),
    (RND, 4, 72, 2),
    (HUB, 6, 168, 41),
    (MULE, 4, 168, 104),
    (PAYROLL, 2, 24, 120),
]


@pytest.fixture
def oracle_settings() -> Settings:
    env = {**read_environ(), "DB_BACKEND": "oracle"}
    for name in ("ORACLE_SYS_PASSWORD", "ORACLE_DEMO_PASSWORD"):
        if not env.get(name):
            pytest.skip(f"{name} is not set in .env")
    return load_settings(environ=env)


def _norm(paths: pd.DataFrame) -> pd.DataFrame:
    """Same frame with timestamps floored to the second (Oracle and DuckDB differ in unit)."""
    out = paths.copy()
    out.columns = [c.lower() for c in out.columns]
    for column in ("first_ts", "last_ts"):
        out[column] = pd.to_datetime(out[column]).dt.floor("s").astype("datetime64[ns]")
    return out.reset_index(drop=True)


def test_ac4_oracle_neo4j_cte_raw_and_pgq_agree(
    neo: Neo, oracle_settings: Settings, tiny_parquet: Path, tmp_path: Path
) -> None:
    load = mod("aml.datagen.load")
    with OracleDb(oracle_settings) as odb:
        load.load_parquet(odb, tiny_parquet)
        mod("aml.entity_resolution.runner").run_er(odb, oracle_settings)
    mod("aml.dba.security").apply_security(oracle_settings)

    with OracleDb(oracle_settings) as odb:
        run = run_sync(odb, oracle_settings, full=True)
        assert run.source_backend == "oracle"
        assert run.graph == s11(*TINY_S11)
        for account, hops, hours, expected in CASES:
            kw = {"hops": hops, "hours": hours, "record_audit": False}
            via_neo = trace(odb, oracle_settings, account, method="neo4j", **kw)
            via_raw = trace(odb, oracle_settings, account, method="cte_raw", **kw)
            via_pgq = trace(odb, oracle_settings, account, method="pgq", **kw)
            assert via_neo.backend == "oracle"
            assert via_neo.n_paths == via_raw.n_paths == via_pgq.n_paths == expected
            pd.testing.assert_frame_equal(_norm(via_neo.paths), _norm(via_raw.paths))
            pd.testing.assert_frame_equal(_norm(via_neo.paths), _norm(via_pgq.paths))

    with DuckDb(tmp_path / "empty.duckdb") as ddb:
        mod("aml.dba.schema").apply_schema(ddb)
        unavailable = mod("aml.graph.model").TraceUnavailableError
        with pytest.raises(
            unavailable, match="graph was synced from oracle but the database is duckdb"
        ):
            trace(ddb, neo_settings(), RND, method="neo4j")
