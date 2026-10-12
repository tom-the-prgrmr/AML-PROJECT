"""AC10 for specs/entity-resolution.md: Oracle and DuckDB give the same entity resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aml.common.config import load_settings, read_environ
from aml.common.db import Database, DuckDb, OracleDb

from .helpers import AS_OF, mod, query, r2, run_er

COUNTS = (
    "customers_resolved",
    "blocked_pairs",
    "match_pairs",
    "review_pairs",
    "clusters",
    "merged_clusters",
    "merged_cifs",
)
EXPECTED_COUNTS = (300, 53, 32, 0, 273, 22, 49)


def _golden(db: Database) -> list[tuple[Any, ...]]:
    df = query(db, "SELECT cif, golden_customer_id, cluster_size FROM customer_golden")
    return sorted((r.cif, r.golden_customer_id, int(r.cluster_size)) for r in df.itertuples())


def _pairs(db: Database, run_id: int) -> list[tuple[Any, ...]]:
    df = query(
        db,
        "SELECT cif_l, cif_r, decision, reason, match_weight FROM er_pairs "
        f"WHERE run_id = {run_id}",
    )
    return sorted(
        (r.cif_l, r.cif_r, r.decision, r.reason, r2(r.match_weight)) for r in df.itertuples()
    )


@pytest.mark.oracle
def test_ac10_oracle_and_duckdb_agree_on_tiny(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    load = mod("aml.datagen.load")
    schema = mod("aml.dba.schema")
    evaluate = mod("aml.entity_resolution.evaluate")
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle")})
    with OracleDb(osettings) as odb:
        load.load_parquet(odb, tiny_parquet)
        orun = run_er(odb, osettings, as_of=AS_OF)
        rid = orun.run_id
        ogolden = _golden(odb)
        opairs = _pairs(odb, rid)
        tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
        views = set(odb.query_df("SELECT view_name FROM user_views").iloc[:, 0])
        weights = query(odb, "SELECT * FROM er_cluster_weights")
        n_audit = int(
            odb.query_df(
                "SELECT COUNT(*) FROM audit_log WHERE module = 'entity_resolution' AND ("
                "(entity_type = 'golden_customer' AND JSON_VALUE(details, '$.run_id') = "
                f"'{rid}') OR (entity_type = 'er_pair' AND JSON_VALUE(details, '$.run_id') = "
                f"'{rid}') OR (entity_type = 'er_run' AND entity_id = '{rid}'))"
            ).iloc[0, 0]
        )
        oeval = evaluate.evaluate_er(odb)
        schema.apply_schema(odb)  # idempotent on a second call

    assert {"ER_RUNS", "ER_MODEL", "ER_PAIRS", "ER_GOLDEN"} <= tables
    assert {"CUSTOMER_GOLDEN", "ER_CLUSTER_WEIGHTS"} <= views
    assert len(weights) == 22
    row = weights[weights["golden_customer_id"] == "G-CIF00000047"].iloc[0]
    assert (r2(row["min_match_weight"]), r2(row["avg_match_weight"])) == (37.00, 40.82)
    assert n_audit == 23
    oeval.columns = [c.lower() for c in oeval.columns]
    assert list(oeval["level"]) == ["pairwise", "cluster"]
    cols = ["predicted", "truth", "tp", "fp", "fn", "precision", "recall"]
    assert tuple(oeval.iloc[0][cols]) == (32, 32, 32, 0, 0, 1.0, 1.0)
    assert tuple(oeval.iloc[1][cols]) == (22, 22, 22, 0, 0, 1.0, 1.0)

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb"})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        load.load_parquet(ddb, tiny_parquet)
        drun = run_er(ddb, dsettings, as_of=AS_OF)
        dgolden = _golden(ddb)
        dpairs = _pairs(ddb, drun.run_id)

    assert tuple(getattr(orun, f) for f in COUNTS) == EXPECTED_COUNTS
    for field in COUNTS:
        assert getattr(orun, field) == getattr(drun, field), field
    assert ogolden == dgolden
    assert opairs == dpairs
