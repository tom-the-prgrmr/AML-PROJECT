"""AC10 for specs/ml-governance.md: Oracle and DuckDB draw, measure, train and write cards alike.

The Oracle schema is shared and keeps its history (`audit_log` cannot be purged; sample, model
and evaluation ids only grow), so no history-dependent number is asserted: ids come from the
returned objects, audit rows are filtered by the ids just created, and `version_gaps` looks only
at rows written since the test started. The test removes the dispositions and good-guy rows it
wrote, in `finally`: a leftover decision on a TINY case would change the numbers of other Oracle
tests on the next run.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import Database, DuckDb, OracleDb
from tests.cases.helpers import AS_OF, approx_equal, js, mod, query
from tests.cases.prio_helpers import PINNED, make_tiny_l

from .helpers import SAMPLE, audit_check, btl, btl_model, cards, prio


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


def _audit_count(db: Database, decision: str, key: str, value: int) -> int:
    field = audit_check().json_text(db, key)
    where = f"module = 'cases' AND decision = '{decision}' AND {field} = '{value}'"
    return int(db.query_df(f"SELECT COUNT(*) FROM audit_log WHERE {where}").iloc[0, 0])


def _members(sample: Any) -> list[tuple[str, str, tuple[str, ...], str]]:
    """Members with the case run number taken out of the reason: Oracle keeps its run history."""
    return [
        (
            m.golden_customer_id,
            m.label,
            m.typologies,
            re.sub(r"case run \d+", "case run N", m.reason),
        )
        for m in sample.members
    ]


def _gather(
    db: Database, settings: Settings, parquet: Path, out: Path, started: datetime
) -> SimpleNamespace:
    _build_sources(db, settings, parquet)
    make_tiny_l(db, settings)
    prio().train(db, settings, actor="analyst01")
    sample = btl().draw_sample(db, settings)
    written = btl().write_btl_features(db, settings, sample.sample_id)
    features = btl().read_btl_features(db, settings, sample.sample_id)
    evaluation = btl_model().evaluate_btl(db, settings, actor="analyst01")
    trained = btl_model().train_with_btl(db, settings, actor="analyst01")
    report = cards().write_cards(db, settings, out_dir=out, names=["prioritization"])
    stored = query(db, f"SELECT scores FROM btl_evaluations WHERE eval_id = {evaluation.eval_id}")
    model = query(db, f"SELECT * FROM case_models WHERE model_id = {trained.training.model_id}")
    return SimpleNamespace(
        sample=sample, written=written, features=features, evaluation=evaluation, trained=trained,
        report=report, scores=js(stored["scores"].iloc[0]), model=model.iloc[0],
        gaps=audit_check().version_gaps(db, since=started),
        labelled=_audit_count(db, "BTL_LABELLED", "sample_id", sample.sample_id),
        sampled=_audit_count(db, "BTL_SAMPLED", "sample_id", sample.sample_id),
        evaluated=_audit_count(db, "BTL_EVALUATED", "eval_id", evaluation.eval_id),
        model_rows=_audit_count(db, "MODEL_TRAINED", "model_id", trained.training.model_id),
    )  # fmt: skip


def _data_hash_line(path: str) -> str:
    return next(
        ln
        for ln in Path(path).read_text(encoding="utf-8").splitlines()
        if ln.startswith("| Data hash |")
    )


@pytest.mark.oracle
def test_ac10_oracle_and_duckdb_agree(tiny_env: Any, tiny_parquet: Path, tmp_path: Path) -> None:
    schema = mod("aml.dba.schema")
    started = datetime.now(UTC)
    extra = {**PINNED, SAMPLE: "50"}
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle"), **extra})
    with OracleDb(osettings) as odb:
        schema.apply_schema(odb)
        disposition_floor = _max(odb, "case_dispositions", "disposition_id")
        entry_floor = _max(odb, "good_guy_list", "entry_no")
        try:
            o = _gather(odb, osettings, tiny_parquet, tmp_path / "oracle", started)
            tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
            schema.apply_schema(odb)  # idempotent on a second call
        finally:
            _forget(odb, disposition_floor, entry_floor)

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb", **extra})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        d = _gather(ddb, dsettings, tiny_parquet, tmp_path / "duckdb", started)

    for name in ("population", "size", "suspicious", "estimated_missed"):
        assert getattr(o.sample, name) == getattr(d.sample, name), name
    assert (o.sample.population, o.sample.suspicious) == (221, 3)
    assert _members(o.sample) == _members(d.sample)
    assert (o.written, d.written) == (1750, 1750)
    assert approx_equal(o.features.to_dict(), d.features.to_dict(), 1e-9)
    assert approx_equal(o.evaluation.metrics, d.evaluation.metrics, 1e-9)
    assert max(abs(o.scores[g] - d.scores[g]) for g in d.scores) <= 1e-6

    assert o.model["data_hash"] == d.model["data_hash"]
    assert approx_equal(js(o.model["metrics"]), js(d.model["metrics"]), 1e-9)
    for state in (o, d):
        assert re.fullmatch(r"prio/logreg\+btl/\d+", state.trained.training.version)
    assert _data_hash_line(o.report.written[0]) == _data_hash_line(d.report.written[0])

    assert o.gaps == [] and d.gaps == []
    assert {"BTL_SAMPLES", "BTL_MEMBERS", "BTL_FEATURES", "BTL_EVALUATIONS"} <= tables
    assert (o.labelled, o.sampled, o.evaluated, o.model_rows) == (50, 1, 1, 1)
    assert (d.labelled, d.sampled, d.evaluated, d.model_rows) == (50, 1, 1, 1)
