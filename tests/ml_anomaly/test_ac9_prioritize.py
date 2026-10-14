"""AC9 for specs/ml-anomaly.md: case ranking takes the two anomaly columns once a run exists.

TINY-L = `tiny_cases` after `run_cases` (run 1), 11 RULE-only cases FALSE_POSITIVE and 27
NETWORK-only cases SUSPICIOUS, then `run_cases` (run 2). It is built once per file.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb
from tests.cases.helpers import audit_cases, count, duck_settings, js, mod, query
from tests.cases.prio_helpers import all_features, make_tiny_l, prio_mod
from tests.memo.helpers import Stub, classify, risk_script

from .helpers import case_features, run_anomaly


def _dispositions(db: DuckDb) -> tuple[int, dict[str, str]]:
    status = query(db, "SELECT case_id, status FROM cases_current ORDER BY case_id")
    return count(db, "case_dispositions"), dict(
        zip(status["case_id"], status["status"], strict=True)
    )


def _model(db: DuckDb, model_id: int) -> Any:
    return query(db, f"SELECT * FROM case_models WHERE model_id = {model_id}").iloc[0]


def _trained(db: DuckDb, settings: Settings) -> SimpleNamespace:
    t = prio_mod().train(db, settings, actor="analyst01")
    row = _model(db, t.model_id)
    audit = audit_cases(db, f"decision = 'MODEL_TRAINED' AND entity_id = '{t.version}'")
    return SimpleNamespace(run=t, row=row, audit=audit.iloc[0], params=js(row["params"]))


@pytest.fixture(scope="module")
def state(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[SimpleNamespace]:
    path = tmp_path_factory.mktemp("anomaly_prio") / "prio.duckdb"
    shutil.copy(tiny_stages["full"], path)
    db = DuckDb(path)
    settings = duck_settings()
    make_tiny_l(db, settings)
    snap = SimpleNamespace(db=db, settings=settings, steps={})
    guard = _dispositions(db)
    snap.before = _trained(db, settings)  # no anomaly run yet
    snap.score_before = prio_mod().score(db, settings)
    snap.anomaly = run_anomaly(db, settings)
    snap.after = _trained(db, settings)
    snap.stored_run1 = count(db, "case_anomaly_features", "WHERE run_id = 1")
    snap.scored = prio_mod().score(db, settings)
    snap.stored_run2 = count(db, "case_anomaly_features", "WHERE run_id = 2")
    snap.score_audit = audit_cases(db, "decision = 'SCORING_RUN_COMPLETED'")
    snap.anomaly2 = run_anomaly(db, settings)
    snap.rescored = prio_mod().score(db, settings)
    snap.score_audit2 = audit_cases(db, "decision = 'SCORING_RUN_COMPLETED'")
    snap.off = _trained(db, duck_settings(AML__ML__ANOMALY__FEATURES="off"))
    snap.unchanged = guard == _dispositions(db)
    yield snap
    db.close()


def test_ac9_before_a_run_training_is_as_in_7c(state: SimpleNamespace) -> None:
    b = state.before
    assert b.row["feature_version"] == "features/v1"
    assert tuple(js(b.row["features"])) == all_features()
    assert "anomaly" not in b.params
    details = js(b.audit["details"])  # parsed: a dict, not a string to search in
    assert isinstance(details, dict) and "anomaly" not in details
    assert state.score_before.cases == 52


def test_ac9_after_a_run_the_model_uses_the_anomaly_columns(state: SimpleNamespace) -> None:
    a, r = state.after, state.anomaly
    assert a.row["feature_version"] == "features/v1+anom/v1"
    features = tuple(js(a.row["features"]))
    assert features[:35] == all_features()
    extra = features[35:]
    wanted = case_features().ANOMALY_CASE_FEATURES
    assert list(extra) == [f for f in wanted if f in extra]  # an ordered subsequence
    assert a.params["anomaly"]["run_id"] == r.run_id
    assert a.params["anomaly"]["model_version"] == r.model_version
    dropped = set(a.params["anomaly"]["dropped_features"])
    assert set(features) | dropped >= set(wanted)
    artifact = json.loads(a.row["artifact"])
    coef = dict(zip(artifact["features"], artifact["coef"], strict=True))
    assert all(float(coef[f]) >= 0 for f in extra)
    assert a.audit["details"]["anomaly"] == a.params["anomaly"]
    assert state.stored_run1 == 104


def test_ac9_score_uses_the_current_anomaly_run(state: SimpleNamespace) -> None:
    assert state.scored.cases == 52
    assert state.stored_run2 == 104
    version = state.after.params["anomaly"]["model_version"]
    first = js(state.score_audit.iloc[-1]["details"])["anomaly_features"]
    assert first == {"trained_version": version, "used_version": version}


def test_ac9_a_newer_run_is_used_and_the_older_one_is_named(state: SimpleNamespace) -> None:
    details = js(state.score_audit2.iloc[-1]["details"])["anomaly_features"]
    assert details["trained_version"] == state.anomaly.model_version
    assert details["used_version"] == state.anomaly2.model_version
    assert details["used_version"] != details["trained_version"]
    assert state.rescored.cases == 52


def test_ac9_features_off_gives_the_7c_model(state: SimpleNamespace) -> None:
    assert state.off.row["feature_version"] == "features/v1"
    assert "anomaly" not in state.off.params
    assert tuple(js(state.off.row["features"])) == all_features()


def test_ac9_no_disposition_or_case_status_changes(state: SimpleNamespace) -> None:
    assert state.unchanged


def test_ac9_memo_and_anomaly_columns_share_the_guarded_fit(tiny_cases: DuckDb) -> None:
    settings = duck_settings()
    make_tiny_l(tiny_cases, settings)
    classify(tiny_cases, settings, Stub(risk_script()))  # every memo has a label: memo columns on
    run = run_anomaly(tiny_cases, settings)
    t = _trained(tiny_cases, settings)
    assert t.row["feature_version"] == "features/v1+memo/v1+anom/v1"
    assert "memo" in t.params and "anomaly" in t.params
    features = tuple(js(t.row["features"]))
    assert features[:35] == all_features()
    memo_cols = mod("aml.memo.features").MEMO_FEATURES
    anomaly_cols = case_features().ANOMALY_CASE_FEATURES
    assert t.params["anomaly"]["model_version"] == run.model_version
    memo_dropped = set(t.params["memo"]["dropped_features"])
    anomaly_dropped = set(t.params["anomaly"]["dropped_features"])
    assert memo_dropped <= set(memo_cols) and anomaly_dropped <= set(anomaly_cols)
    assert set(features) | memo_dropped >= set(memo_cols)
    assert set(features) | anomaly_dropped >= set(anomaly_cols)
    assert not (set(features) & (memo_dropped | anomaly_dropped))


def test_ac9_lightgbm_drops_every_anomaly_column(tiny_cases: DuckDb) -> None:
    pytest.importorskip("lightgbm")
    settings = duck_settings()
    make_tiny_l(tiny_cases, settings)
    run_anomaly(tiny_cases, settings)
    t = prio_mod().train(tiny_cases, settings, kind="lightgbm", actor="analyst01")
    row = _model(tiny_cases, t.model_id)
    params = js(row["params"])
    wanted = list(case_features().ANOMALY_CASE_FEATURES)
    assert row["feature_version"] == "features/v1+anom/v1"
    assert tuple(js(row["features"])) == all_features()
    assert params["anomaly"]["dropped_features"] == wanted
    s = prio_mod().score(tiny_cases, settings, actor="analyst01")
    assert s.cases == 52
    # no anomaly column is left in the model: nothing is written for run 2 and nothing is audited
    assert count(tiny_cases, "case_anomaly_features", "WHERE run_id = 2") == 0
    audit = audit_cases(tiny_cases, "decision = 'SCORING_RUN_COMPLETED'")
    assert "anomaly_features" not in js(audit.iloc[-1]["details"])
