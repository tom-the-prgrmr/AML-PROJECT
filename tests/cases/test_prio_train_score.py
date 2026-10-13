"""AC5, AC6 and the database half of AC7 for specs/case-prioritization.md: `train` and `score`.

TINY-L = `tiny_cases` after `run_cases` (run 1), 11 RULE-only cases FALSE_POSITIVE and 27
NETWORK-only cases SUSPICIOUS by analyst01, then `run_cases` (run 2). The two expensive states are
built once per file by `Lazy` (inside the first test that needs them, so a missing module is a
test failure and not a fixture error) and only read afterwards.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import (
    TINY_CASE,
    audit_cases,
    count,
    duck_settings,
    js,
    load_case,
    query,
    run_cases,
)
from .prio_helpers import (
    Lazy,
    all_features,
    features_mod,
    make_tiny_l,
    numpy_scores,
    prio_error,
    prio_mod,
    source_of,
    state_digest,
    text,
)

VERSION = "prio/logreg/1"
FEATURES = all_features()


def _new_db(stages: dict[str, Path], factory: pytest.TempPathFactory, name: str) -> DuckDb:
    path = factory.mktemp(name) / f"{name}.duckdb"
    shutil.copy(stages["full"], path)
    return DuckDb(path)


def _model_rows(db: DuckDb) -> pd.DataFrame:
    return query(db, "SELECT * FROM case_models ORDER BY model_id")


# ---------------------------------------------------------------- AC5 state: two trainings
def _build_trained(stages: dict[str, Path], factory: pytest.TempPathFactory) -> SimpleNamespace:
    db = _new_db(stages, factory, "prio_trained")
    settings = duck_settings()
    make_tiny_l(db, settings)
    prio = prio_mod()
    before = state_digest(db)
    first = prio.train(db, settings, actor="analyst01")
    snap = SimpleNamespace(
        db=db,
        first=first,
        models1=_model_rows(db),
        audit1=audit_cases(db, "decision = 'MODEL_TRAINED'"),
        features_run1=count(db, "case_features", "WHERE run_id = 1"),
        active1=query(db, "SELECT model_id FROM case_model_active"),
    )
    snap.second = prio.train(db, settings, actor="analyst01")
    snap.models2 = _model_rows(db)
    snap.active2 = query(db, "SELECT model_id FROM case_model_active")
    snap.unchanged = before == state_digest(db)
    return snap


_TRAINED = Lazy(_build_trained)


def test_ac5_train_stores_a_versioned_model_with_its_audit_row(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    s = _TRAINED.get(tiny_stages, tmp_path_factory)
    t = s.first
    assert (t.model_id, t.version, t.kind) == (1, VERSION, "logreg")
    assert (t.cases, t.suspicious, t.false_positive) == (38, 27, 11)
    assert t.metrics["n"] == 38
    assert t.metrics["prevalence"] == 0.7105
    assert t.metrics["roc_auc"] >= 0.9  # the two classes differ in `network_alerts`
    for name in ("precision_at", "recall_at"):
        assert all(0.0 <= v <= 1.0 for v in t.metrics[name].values()), name

    assert len(s.models1) == 1
    row = s.models1.iloc[0]
    assert (row["version"], row["feature_version"], row["seed"]) == (VERSION, "features/v1", 42)
    assert (row["cases"], row["suspicious"], row["false_positive"]) == (38, 27, 11)
    assert row["actor"] == "analyst01"
    assert js(row["features"]) == list(FEATURES)
    params = js(row["params"])
    assert params["class_weight"] == "balanced"
    assert params["cv_folds"] == 5
    import sklearn

    assert str(params["sklearn"]).startswith(sklearn.__version__)
    assert re.fullmatch(r"[0-9a-f]{16}", row["data_hash"])
    assert js(row["metrics"])["n"] == 38

    # the features come from the snapshot the 38 dispositions saw (run 1)
    assert s.features_run1 == 52 * 35


def test_ac5_train_is_audited_with_the_version_and_the_data_hash(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    s = _TRAINED.get(tiny_stages, tmp_path_factory)
    assert len(s.audit1) == 1
    a = s.audit1.iloc[0]
    assert (a["entity_type"], a["entity_id"], a["version"], a["actor"]) == (
        "model",
        VERSION,
        VERSION,
        "analyst01",
    )
    assert a["reason"].startswith(
        "trained logreg on 38 labelled cases (27 SUSPICIOUS, 11 FALSE_POSITIVE; "
        "class_weight balanced)"
    )
    assert a["reason"].endswith("ranking only")
    assert a["details"]["data_hash"] == s.models1.iloc[0]["data_hash"]
    assert a["details"]["model_id"] == 1


def test_ac5_second_training_is_a_new_version_of_the_same_model(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    s = _TRAINED.get(tiny_stages, tmp_path_factory)
    t1, t2 = s.first, s.second
    assert (t2.model_id, t2.version) == (2, "prio/logreg/2")
    assert t2.metrics == t1.metrics
    one, two = s.models2.iloc[0], s.models2.iloc[1]
    assert len(s.models2) == 2
    assert one["data_hash"] == two["data_hash"]
    assert text(one["artifact"]) == text(two["artifact"])
    assert js(one["metrics"]) == js(two["metrics"])
    assert s.active1["model_id"].tolist() == [1]
    assert s.active2["model_id"].tolist() == [2]


def test_ac5_training_never_touches_cases_or_dispositions(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    assert _TRAINED.get(tiny_stages, tmp_path_factory).unchanged


def test_ac5_nothing_labelled_is_refused_and_nothing_is_written(tiny_cases: DuckDb) -> None:
    settings = duck_settings()
    run_cases(tiny_cases, settings)
    with pytest.raises(prio_error(), match="not enough labelled cases") as exc:
        prio_mod().train(tiny_cases, settings)
    assert "need at least 5 per class, got SUSPICIOUS=0 FALSE_POSITIVE=0" in str(exc.value)
    assert count(tiny_cases, "case_models") == 0
    assert count(tiny_cases, "case_features") == 0
    assert audit_cases(tiny_cases, "decision = 'MODEL_TRAINED'").empty


def test_ac5_only_suspicious_labels_are_refused(tiny_cases: DuckDb) -> None:
    from .prio_helpers import FRACTION, labels_mod

    settings = duck_settings(**{FRACTION: "1.0"})
    run_cases(tiny_cases, settings)
    labels_mod().simulate_dispositions(tiny_cases, settings)
    with pytest.raises(prio_error(), match=re.escape("got SUSPICIOUS=52 FALSE_POSITIVE=0")):
        prio_mod().train(tiny_cases, settings)
    assert count(tiny_cases, "case_models") == 0


# ----------------------------------------------------- AC6 state: one model, two scorings
def _build_scored(stages: dict[str, Path], factory: pytest.TempPathFactory) -> SimpleNamespace:
    db = _new_db(stages, factory, "prio_scored")
    settings = duck_settings()
    make_tiny_l(db, settings)
    prio = prio_mod()
    prio.train(db, settings, actor="analyst01")
    before = state_digest(db)
    n_open_before = count(db, "cases_current", "WHERE status = 'OPEN'")

    s1 = prio.score(db, settings, actor="analyst01")
    snap = SimpleNamespace(db=db, s1=s1, before=before, n_open_before=n_open_before)
    snap.after1 = state_digest(db)
    snap.n_open_after = count(db, "cases_current", "WHERE status = 'OPEN'")
    snap.scores1 = query(
        db,
        "SELECT s.*, c.status FROM case_scores s JOIN cases_current c ON c.case_id = s.case_id "
        "WHERE s.score_run_id = 1 ORDER BY s.case_id",
    )
    snap.queue1 = query(db, "SELECT * FROM case_queue ORDER BY queue_rank")
    snap.prioritized = audit_cases(db, "decision = 'PRIORITIZED'")
    snap.completed = audit_cases(db, "decision = 'SCORING_RUN_COMPLETED'")
    snap.view = load_case(db, TINY_CASE).score
    snap.model = _model_rows(db).iloc[0]

    s2 = prio.score(db, settings, actor="analyst01")
    snap.s2 = s2
    snap.scores2 = query(db, "SELECT * FROM case_scores WHERE score_run_id = 2 ORDER BY case_id")
    snap.current = query(db, "SELECT * FROM case_scores_current ORDER BY case_id")
    snap.rows_before_bad = count(db, "case_scores")
    try:
        prio.score(db, settings, model_id=99)
        snap.unknown_error = None
    except Exception as exc:
        snap.unknown_error = exc
    snap.rows_after_bad = count(db, "case_scores")
    return snap


_SCORED = Lazy(_build_scored)


def _scored(stages: dict[str, Path], factory: pytest.TempPathFactory) -> SimpleNamespace:
    return _SCORED.get(stages, factory)  # type: ignore[no-any-return]


def test_ac6_scoring_run_summary(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    s = _scored(tiny_stages, tmp_path_factory)
    r = s.s1
    assert (r.score_run_id, r.run_id, r.model_id, r.version) == (1, 2, 1, VERSION)
    assert (r.cases, r.queue) == (52, 14)
    assert len(s.scores1) == 52
    assert set(s.scores1["model_version"]) == {VERSION}
    assert set(s.scores1["run_id"]) == {2}
    assert set(s.scores1["model_id"]) == {1}
    for value in s.scores1["score"]:
        assert 0.0 <= value <= 1.0  # a cut-off case can round to 0.0 or 1.0 at 6 decimals
        assert abs(round(value, 6) - value) < 1e-9  # at most 6 decimals


def test_ac6_queue_rank_orders_the_open_cases_only(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    df = _scored(tiny_stages, tmp_path_factory).scores1
    open_ = df[df["status"] == "OPEN"]
    closed = df[df["status"] == "CLOSED"]
    assert (len(open_), len(closed)) == (14, 38)
    assert sorted(open_["queue_rank"].astype(int)) == list(range(1, 15))
    assert closed["queue_rank"].isna().all()
    ranked = open_.sort_values("queue_rank")
    expected = sorted(zip(-ranked["score"], ranked["case_id"], strict=True))
    assert [c for _, c in expected] == list(ranked["case_id"])  # score down, case_id up on ties


def test_ac6_top_features_explain_each_score(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    df = _scored(tiny_stages, tmp_path_factory).scores1
    for case_id, raw in zip(df["case_id"], df["top_features"], strict=True):
        top = js(raw)
        assert len(top) == 5, case_id
        names = [t["feature"] for t in top]
        assert all(set(t) == {"feature", "value", "contribution"} for t in top)
        assert set(names) <= set(FEATURES)
        assert len(set(names)) == 5
        magnitudes = [abs(t["contribution"]) for t in top]
        assert magnitudes == sorted(magnitudes, reverse=True), case_id


def test_ac6_scores_can_be_recomputed_from_the_stored_artifact_with_numpy_only(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    s = _scored(tiny_stages, tmp_path_factory)
    features = features_mod().read_features(s.db, 2)
    assert len(features) == 52
    expected = numpy_scores(text(s.model["artifact"]), features)
    got = s.scores1.set_index("case_id")["score"]
    for case_id in got.index:
        assert abs(got[case_id] - expected[case_id]) <= 1e-6, case_id


def test_ac6_case_queue_lists_the_open_cases(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    q = _scored(tiny_stages, tmp_path_factory).queue1
    assert len(q) == 14
    assert q["queue_rank"].astype(int).tolist() == list(range(1, 15))


def test_ac6_case_view_carries_the_score(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    view = _scored(tiny_stages, tmp_path_factory).view
    assert view is not None
    assert {"score", "queue_rank", "model_version", "top_features"} <= set(view)
    assert view["model_version"] == VERSION


def test_ac6_every_score_is_audited_with_the_model_version(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    s = _scored(tiny_stages, tmp_path_factory)
    # the fixture scored twice; the first scoring run owns the rows with score_run_id 1
    first = s.prioritized[[d["score_run_id"] == 1 for d in s.prioritized["details"]]]
    assert len(first) == 52
    table = s.scores1.set_index("case_id")["score"]
    status = s.scores1.set_index("case_id")["status"]
    for row in first.itertuples():
        assert row.entity_type == "case"
        assert row.version == VERSION
        assert row.details["model_id"] == 1
        assert abs(row.details["score"] - table[row.entity_id]) <= 1e-9
        assert row.reason.startswith("priority score ")
        assert f"from {VERSION}" in row.reason
        assert row.reason.endswith("ranking only, no disposition")
        if status[row.entity_id] == "CLOSED":
            assert "not in the queue (CLOSED)" in row.reason
        else:
            assert "queue rank " in row.reason and " of 14" in row.reason
    completed = s.completed[[d["score_run_id"] == 1 for d in s.completed["details"]]]
    assert len(completed) == 1
    assert completed.iloc[0]["entity_type"] == "case_run"


def test_ac6_holdout_is_measured_against_the_truth_but_has_one_class(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    h = _scored(tiny_stages, tmp_path_factory).s1.holdout
    assert (h["n"], h["n_suspicious"], h["prevalence"]) == (14, 14, 1.0)
    assert h["roc_auc"] is None  # every case still open in TINY is a real hit


def test_ac6_the_model_only_ranks(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    s = _scored(tiny_stages, tmp_path_factory)
    assert s.after1 == s.before
    assert s.n_open_before == s.n_open_after == 14
    assert "record_disposition" not in source_of("aml.cases.prioritize")
    assert "record_disposition" not in source_of("aml.cases.model")


def test_ac6_a_second_scoring_run_replaces_the_first_in_the_current_view(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    s = _scored(tiny_stages, tmp_path_factory)
    assert s.s2.score_run_id == 2
    for column in ("score", "queue_rank"):
        assert s.scores2[column].fillna(-1).tolist() == s.scores1[column].fillna(-1).tolist()
    first = [js(x) for x in s.scores1["top_features"]]
    second = [js(x) for x in s.scores2["top_features"]]
    assert first == second
    assert len(s.current) == 52
    assert set(s.current["score_run_id"]) == {2}


def test_ac6_unknown_model_id_is_refused(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    s = _scored(tiny_stages, tmp_path_factory)
    assert isinstance(s.unknown_error, prio_error())
    assert "unknown model_id" in str(s.unknown_error)
    assert s.rows_after_bad == s.rows_before_bad == 104


def test_ac6_scoring_without_a_model_is_refused(tiny_cases: DuckDb) -> None:
    settings = duck_settings()
    run_cases(tiny_cases, settings)
    with pytest.raises(prio_error(), match=re.escape("no model: run `aml cases train` first")):
        prio_mod().score(tiny_cases, settings)
    assert count(tiny_cases, "case_scores") == 0


# ------------------------------------------------------- AC7: LightGBM through the database
def test_ac7_lightgbm_train_and_score_record_their_own_version(tiny_cases: DuckDb) -> None:
    pytest.importorskip("lightgbm")
    settings = duck_settings()
    make_tiny_l(tiny_cases, settings)
    prio = prio_mod()
    t = prio.train(tiny_cases, settings, kind="lightgbm", actor="analyst01")
    assert (t.kind, t.version) == ("lightgbm", "prio/lightgbm/1")
    assert text(query(tiny_cases, "SELECT artifact FROM case_models").iloc[0, 0]).startswith("tree")

    r = prio.score(tiny_cases, settings, actor="analyst01")
    assert (r.version, r.cases, r.queue) == ("prio/lightgbm/1", 52, 14)
    assert set(query(tiny_cases, "SELECT model_version FROM case_scores")["model_version"]) == {
        "prio/lightgbm/1"
    }
    rows = audit_cases(tiny_cases, "decision = 'PRIORITIZED'")
    assert len(rows) == 52
    assert set(rows["version"]) == {"prio/lightgbm/1"}
    assert r.holdout["n"] == 14
