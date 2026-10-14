"""AC10 for specs/screening-ml.md: Oracle and DuckDB label, train and score TINY the same way.

The Oracle schema is shared and `audit_log` and the label table are append-only, so this test is
written to be re-run: ids come from the returned runs, `labelled + skipped == 55`, and every
model id is compared relative to the maximum before the call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import Database, DuckDb, OracleDb
from aml.dba.schema import apply_schema

from .helpers import AS_OF, mod, query, scalar

FULL = {"AML__ML__SCREENING__SIMULATE_FRACTION": "1.0"}


def _run(db: Database, settings: Settings, parquet: Path) -> dict[str, Any]:
    mod("aml.datagen.load").load_parquet(db, parquet)
    mod("aml.screening.runner").run_screening(db, settings, as_of=AS_OF)
    labels, pipeline = mod("aml.screening.ml.labels"), mod("aml.screening.ml.pipeline")
    features = mod("aml.screening.ml.features")
    floor = int(scalar(db, "SELECT COALESCE(MAX(model_id), 0) FROM screening_ml_models"))
    sim = labels.simulate_labels(db, settings)
    training = labels.training_labels(db, settings)
    trained = pipeline.train(db, settings, actor="analyst01")
    scored = pipeline.score(db, settings, actor="analyst01")
    artifact = scalar(
        db, f"SELECT artifact FROM screening_ml_models WHERE model_id = {trained.model_id}"
    )
    text = str(artifact.read() if hasattr(artifact, "read") else artifact)
    scores = query(
        db, f"SELECT cif, entry_id, score, score_rank FROM screening_ml_scores "
        f"WHERE score_run_id = {scored.score_run_id} ORDER BY cif, entry_id",
    )  # fmt: skip
    return {
        "floor": floor, "sim": sim, "training": training, "trained": trained, "scored": scored,
        "coef": np.asarray(json.loads(text)["coef"]),
        "scores": scores, "features": features.read_features(db),
    }  # fmt: skip


@pytest.mark.oracle
def test_ac10_oracle_and_duckdb_agree_on_tiny(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle", **FULL)})
    with OracleDb(osettings) as odb:
        apply_schema(odb)
        apply_schema(odb)  # a second run must not raise
        o = _run(odb, osettings, tiny_parquet)
        tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
        views = set(odb.query_df("SELECT view_name FROM user_views").iloc[:, 0])
        run = o["scored"]
        n_audit = int(
            odb.query_df(
                "SELECT COUNT(*) FROM audit_log WHERE module = 'screening_ml' "
                "AND decision = 'ML_SCORED' AND "
                f"JSON_VALUE(details, '$.score_run_id') = '{run.score_run_id}' "
                f"AND version = '{run.version}'"
            ).iloc[0, 0]
        )
    assert {
        "SCREENING_ML_LABELS", "SCREENING_ML_FEATURES", "SCREENING_ML_MODELS",
        "SCREENING_ML_TRAINING", "SCREENING_ML_SCORES",
    } <= tables  # fmt: skip
    assert {"SCREENING_ML_MODEL_ACTIVE", "SCREENING_ML_SCORES_CURRENT"} <= views
    assert n_audit == 55
    assert o["sim"].labelled + o["sim"].skipped == 55
    assert o["trained"].model_id > o["floor"]

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb", **FULL})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        d = _run(ddb, dsettings, tiny_parquet)

    assert len(o["training"]) == len(d["training"]) == 55
    assert int(o["training"]["label"].sum()) == int(d["training"]["label"].sum()) == 5
    assert list(o["training"].index) == list(d["training"].index)
    for field in ("pairs", "true_match", "false_match"):
        assert getattr(o["trained"], field) == getattr(d["trained"], field), field
    assert np.abs(o["coef"] - d["coef"]).max() <= 1e-9
    so, sd = o["scores"], d["scores"]
    assert list(zip(so["cif"], so["entry_id"], strict=True)) == list(
        zip(sd["cif"], sd["entry_id"], strict=True)
    )
    assert (
        np.abs(so["score"].to_numpy(dtype=float) - sd["score"].to_numpy(dtype=float)).max() <= 1e-6
    )
    assert list(so["score_rank"]) == list(sd["score_rank"])
    fo, fd = o["features"].droplevel("result_run_id"), d["features"].droplevel("result_run_id")
    assert np.abs(fo.to_numpy() - fd.to_numpy()).max() <= 1e-9
