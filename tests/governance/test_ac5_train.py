"""AC5 for specs/ml-governance.md: the `+btl` model variant and the per-population metrics."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from aml.common.db import Database
from tests.cases.prio_helpers import copy_tiny, fit_toy, toy_config
from tests.cases.prio_helpers import model_mod as case_model_mod

from .helpers import (
    audit_df,
    btl_model,
    btl_settings,
    build_tiny_l,
    counts,
    js,
    mod,
    prio,
    prio_error,
    query,
    run_cases,
    scalar,
)

FRACTION = "AML__CASES__PRIORITIZATION__SIMULATE_FRACTION"
GUARDED = ("case_dispositions", "cases")


def _row(db: Database, model_id: int) -> tuple[str, ...]:
    df = query(
        db,
        f"SELECT version, artifact, metrics, data_hash FROM case_models "
        f"WHERE model_id = {model_id}",
    )
    return tuple(str(v) for v in df.iloc[0])


@pytest.fixture(scope="module")
def state(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[SimpleNamespace]:
    db, settings = build_tiny_l(tiny_stages, tmp_path_factory)
    base = prio().train(db, settings, actor="analyst01")
    row1 = _row(db, 1)
    before = counts(db, *GUARDED)
    first = btl_model().train_with_btl(db, settings, actor="analyst01")
    active_first = int(query(db, "SELECT model_id FROM case_model_active")["model_id"].iloc[0])
    scored = prio().score(db, settings, actor="analyst01")
    second = btl_model().train_with_btl(db, settings, actor="analyst01")
    plain = prio().train(db, settings)
    yield SimpleNamespace(
        db=db, settings=settings, base=base, row1=row1, before=before, first=first,
        scored=scored, active_first=active_first, second=second, plain=plain,
    )  # fmt: skip
    db.close()


def test_ac5_the_variant_and_its_counts(state: SimpleNamespace) -> None:
    r = state.first
    t = r.training
    assert (t.model_id, t.version, t.kind) == (2, "prio/logreg+btl/2", "logreg")
    assert (t.cases, t.suspicious, t.false_positive) == (88, 30, 58)
    assert state.active_first == 2
    assert r.alerted == (27, 11) and r.below_the_line == (3, 47)
    m = t.metrics
    assert (m["n"], m["prevalence"]) == (88, 0.3409)
    alerted, below = m["by_population"]["alerted"], m["by_population"]["below_the_line"]
    assert (alerted["n"], alerted["prevalence"]) == (38, 0.7105)
    assert (below["n"], below["n_suspicious"], below["prevalence"]) == (50, 3, 0.06)


def test_ac5_model_one_is_untouched_and_two_is_stored(state: SimpleNamespace) -> None:
    db, r = state.db, state.first
    assert _row(db, 1) == state.row1
    params = js(query(db, "SELECT params FROM case_models WHERE model_id = 2")["params"].iloc[0])
    assert params["population"] == {
        "alerted": [27, 11], "below_the_line": [3, 47], "btl_sample_id": r.sample_id,
    }  # fmt: skip
    assert params["class_weight"] == "balanced"
    active = query(db, "SELECT model_id FROM case_model_active")
    assert int(active["model_id"].iloc[0]) == 4  # the 7c train at the end is the newest


def test_ac5_the_audit_row(state: SimpleNamespace) -> None:
    rows = audit_df(state.db, "decision = 'MODEL_TRAINED' AND version = 'prio/logreg+btl/2'")
    assert len(rows) == 1
    a = rows.iloc[0]
    assert a["reason"].startswith(
        "trained logreg on 38 labelled cases (27 SUSPICIOUS, 11 FALSE_POSITIVE) and 50 "
        "below-the-line customers (3 SUSPICIOUS, 47 NOT_SUSPICIOUS; sample"
    )
    assert a["reason"].endswith("ranking only")
    assert (a["actor"], a["entity_id"]) == ("analyst01", "prio/logreg+btl/2")
    assert a["details"]["population"]["alerted"] == [27, 11]


def test_ac5_score_after_the_variant_carries_its_version(state: SimpleNamespace) -> None:
    db, s = state.db, state.scored
    assert s.version == "prio/logreg+btl/2" and s.queue == 14
    scores = query(
        db, f"SELECT model_version FROM case_scores WHERE score_run_id = {s.score_run_id}"
    )
    assert len(scores) == 52 and set(scores["model_version"]) == {"prio/logreg+btl/2"}
    prioritized = audit_df(db, "decision = 'PRIORITIZED' AND version = 'prio/logreg+btl/2'")
    assert len(prioritized) == 52


def test_ac5_a_repeat_gives_the_same_model_and_7c_is_unchanged(state: SimpleNamespace) -> None:
    a, b = state.first.training, state.second.training
    assert b.version == "prio/logreg+btl/3"
    assert _row(state.db, 2)[1:] == _row(state.db, 3)[1:]
    assert a.metrics == b.metrics
    assert state.plain.version == "prio/logreg/4"
    assert _row(state.db, 4)[3] == state.row1[3]  # the 7c data_hash of model 1
    assert "by_population" not in state.plain.metrics


def test_ac5_no_case_or_disposition_is_written(state: SimpleNamespace) -> None:
    assert counts(state.db, *GUARDED) == state.before


def test_ac5_fit_model_without_populations_is_as_before() -> None:
    model, X, y, groups = fit_toy()
    assert "by_population" not in model.metrics
    fm = case_model_mod()
    assert model.data_hash == fm._data_hash(X.sort_index(), y.loc[X.sort_index().index])
    populations = pd.Series(
        {i: "alerted" if int(i[3:5]) % 2 else "below_the_line" for i in X.index}
    )
    with_pop = fm.fit_model(X, y, groups, toy_config(), seed=42, populations=populations)
    assert with_pop.data_hash == model.data_hash and with_pop.artifact == model.artifact
    assert set(with_pop.metrics["by_population"]) == {"alerted", "below_the_line"}


def test_ac5_all_cases_suspicious_still_trains_with_the_sample(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    db = copy_tiny(tiny_stages, tmp_path_factory.mktemp("btl_sim") / "sim.duckdb")
    settings = btl_settings(**{FRACTION: "1.0"})
    try:
        run_cases(db, settings)
        mod("aml.cases.labels").simulate_dispositions(db, settings)
        assert scalar(db, "SELECT COUNT(*) FROM case_dispositions") == 52
        with pytest.raises(prio_error(), match="got SUSPICIOUS=52 FALSE_POSITIVE=0"):
            prio().train(db, settings)
        r = btl_model().train_with_btl(db, settings)
        t = r.training
        assert (t.cases, t.suspicious, t.false_positive) == (102, 55, 47)
        assert t.metrics["by_population"]["alerted"]["roc_auc"] is None

        small = btl_settings(20, **{FRACTION: "1.0"})
        r20 = btl_model().train_with_btl(db, small)
        assert r20.training.suspicious == 52 and r20.below_the_line == (0, 20)
    finally:
        db.close()


def test_ac5_a_class_with_too_few_rows_stops_before_a_model_is_written(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    db = copy_tiny(tiny_stages, tmp_path_factory.mktemp("btl_few") / "few.duckdb")
    settings = btl_settings(20)
    try:
        run_cases(db, settings)
        match = (
            "not enough labelled rows: need at least 5 per class, "
            "got SUSPICIOUS=0 NOT_SUSPICIOUS=20"
        )
        with pytest.raises(prio_error(), match=match):
            btl_model().train_with_btl(db, settings)
        assert counts(db, "case_models") == [0]
    finally:
        db.close()
