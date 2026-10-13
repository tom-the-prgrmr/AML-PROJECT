"""AC9 for specs/case-prioritization.md: Oracle and DuckDB train and score the same way on TINY-L.

The Oracle schema is shared and keeps its history (`audit_log` cannot be purged, model ids and
score runs only grow), so no history-dependent constant is asserted: ids come from the returned
`TrainingRun` / `ScoringRun`, and the audit rows are filtered by the score run just created. The
test removes the dispositions and good-guy rows it wrote, in `finally`: a leftover decision on a
TINY case would change the numbers of `test_oracle_parity.py` and `test_supp_oracle.py` on the next
run.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import Database, DuckDb, OracleDb

from .helpers import AS_OF, approx_equal, js, mod, query
from .prio_helpers import PINNED, features_mod, make_tiny_l, prio_mod, text


def _build_sources(db: Database, settings: Settings, parquet: Path) -> None:
    mod("aml.datagen.load").load_parquet(db, parquet)
    mod("aml.entity_resolution.runner").run_er(db, settings, as_of=AS_OF)
    mod("aml.screening.runner").run_screening(db, settings, as_of=AS_OF)
    mod("aml.monitoring.runner").run_monitoring(db, settings, as_of=AS_OF)
    mod("aml.graph.network.runner").run_network(db, settings, as_of=AS_OF)
    mod("aml.dq.runner").run_dq(db, settings, as_of=AS_OF)


def _max(db: Database, table: str, column: str) -> int:
    return int(db.query_df(f"SELECT COALESCE(MAX({column}), 0) FROM {table}").iloc[0, 0])


def _forget(db: Database, disposition_floor: int, entry_floor: int) -> None:
    """Remove the decisions (and what they produced) this test wrote; best effort."""
    for table, column, floor in (
        ("good_guy_list", "entry_no", entry_floor),
        ("case_dispositions", "disposition_id", disposition_floor),
    ):
        try:
            db.execute(f"DELETE FROM {table} WHERE {column} > {floor}")
        except Exception:
            continue


def _gather(db: Database, settings: Settings, parquet: Path) -> SimpleNamespace:
    """Build TINY-L on ``db``, train, score; return what the two backends are compared on."""
    _build_sources(db, settings, parquet)
    make_tiny_l(db, settings)  # run_cases, 38 decisions, run_cases
    prio = prio_mod()
    t = prio.train(db, settings, actor="analyst01")
    s = prio.score(db, settings, actor="analyst01")
    model = query(db, f"SELECT * FROM case_models WHERE model_id = {t.model_id}").iloc[0]
    scores = query(
        db,
        "SELECT case_id, score, queue_rank FROM case_scores "
        f"WHERE score_run_id = {s.score_run_id} ORDER BY case_id",
    )
    return SimpleNamespace(
        training=t,
        scoring=s,
        model=model,
        artifact=json.loads(text(model["artifact"])),
        metrics=js(model["metrics"]),
        scores=scores,
        features=features_mod().read_features(db, s.run_id),
    )


def _audit_counts(db: Database, state: SimpleNamespace) -> tuple[int, int]:
    """PRIORITIZED rows of the score run just created, and how many carry another version."""
    rid = state.scoring.score_run_id
    where = (
        "module = 'cases' AND decision = 'PRIORITIZED' "
        f"AND JSON_VALUE(details, '$.score_run_id') = '{rid}'"
    )
    total = int(db.query_df(f"SELECT COUNT(*) FROM audit_log WHERE {where}").iloc[0, 0])
    version = state.scoring.version
    other = int(
        db.query_df(
            f"SELECT COUNT(*) FROM audit_log WHERE {where} AND version <> '{version}'"
        ).iloc[0, 0]
    )
    return total, other


def _compare(o: SimpleNamespace, d: SimpleNamespace) -> None:
    for name in ("cases", "suspicious", "false_positive"):
        assert getattr(o.training, name) == getattr(d.training, name), name
        assert o.model[name] == d.model[name], name
    assert (o.training.cases, o.training.suspicious, o.training.false_positive) == (38, 27, 11)
    assert o.model["data_hash"] == d.model["data_hash"]
    assert approx_equal(o.metrics, d.metrics, 1e-9)
    assert approx_equal(o.training.metrics, d.training.metrics, 1e-9)
    assert o.artifact["features"] == d.artifact["features"]
    coef_o = np.asarray(o.artifact["coef"], dtype=float).ravel()
    coef_d = np.asarray(d.artifact["coef"], dtype=float).ravel()
    assert float(np.abs(coef_o - coef_d).max()) <= 1e-9

    assert len(o.scores) == len(d.scores) == o.scoring.cases == d.scoring.cases == 52
    assert o.scores["case_id"].tolist() == d.scores["case_id"].tolist()
    gap = (o.scores["score"] - d.scores["score"]).abs().max()
    assert float(gap) <= 1e-6
    ranks_o = o.scores["queue_rank"].fillna(-1).astype(int).tolist()
    ranks_d = d.scores["queue_rank"].fillna(-1).astype(int).tolist()
    assert ranks_o == ranks_d
    assert o.scoring.queue == d.scoring.queue == 14

    pd.testing.assert_frame_equal(
        o.features.astype(float), d.features.astype(float), check_exact=False, atol=1e-9, rtol=0
    )


@pytest.mark.oracle
def test_ac9_oracle_and_duckdb_agree_on_training_and_scoring(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    schema = mod("aml.dba.schema")
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle"), **PINNED})
    with OracleDb(osettings) as odb:
        schema.apply_schema(odb)
        disposition_floor = _max(odb, "case_dispositions", "disposition_id")
        entry_floor = _max(odb, "good_guy_list", "entry_no")
        try:
            ostate = _gather(odb, osettings, tiny_parquet)
            tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
            views = set(odb.query_df("SELECT view_name FROM user_views").iloc[:, 0])
            audited, other_version = _audit_counts(odb, ostate)
            schema.apply_schema(odb)  # idempotent on a second call
        finally:
            _forget(odb, disposition_floor, entry_floor)

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb", **PINNED})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        dstate = _gather(ddb, dsettings, tiny_parquet)

    _compare(ostate, dstate)
    assert {"CASE_FEATURES", "CASE_MODELS", "CASE_SCORES"} <= tables
    assert {"CASE_MODEL_ACTIVE", "CASE_SCORES_CURRENT", "CASE_QUEUE"} <= views
    assert audited == 52
    assert other_version == 0  # every row carries the Oracle model's version
