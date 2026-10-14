"""AC2 for specs/ml-governance.md: the pure functions and the below-the-line sample of TINY-B."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.cases.prio_helpers import copy_tiny

from .helpers import (
    audit_df,
    btl,
    btl_settings,
    build_tiny_b,
    case_error,
    count,
    decision_digest,
    prio_error,
    query,
    scalar,
)

SUSPICIOUS_IDS = ["G-CIF00000201", "G-CIF00000242", "G-CIF00000300"]
FIRST_IDS = ["G-CIF00000018", "G-CIF00000019", "G-CIF00000020"]
SAMPLE_TABLES = ("btl_samples", "btl_members", "btl_features", "btl_evaluations")


def test_ac2_seeded_positions() -> None:
    f = btl().seeded_positions
    assert f(42, 10, 3) == [0, 6, 9]
    assert f(42, 5, 9) == [0, 1, 2, 3, 4]
    assert f(42, 0, 3) == []


def test_ac2_wilson_interval() -> None:
    f = btl().wilson_interval
    assert f(3, 50) == (0.0206, 0.1622)
    assert f(0, 20) == (0.0, 0.1611)
    assert f(0, 0) == (None, None)


def test_ac2_btl_label_is_pure() -> None:
    none = btl().btl_label("G-X", 1, [])
    assert (none.label, none.typologies) == ("NOT_SUSPICIOUS", ())
    assert (
        none.reason
        == "below-the-line sample: not alerted in case run 1 and in no suspicious scenario"
    )
    sus = btl().btl_label("G-X", 1, ["rapid_movement", "mule_ring", "rapid_movement"])
    assert (sus.label, sus.typologies) == ("SUSPICIOUS", ("mule_ring", "rapid_movement"))
    assert sus.reason == (
        "below-the-line sample: not alerted in case run 1, but in a suspicious scenario "
        "(mule_ring, rapid_movement)"
    )


@pytest.fixture(scope="module")
def state(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[SimpleNamespace]:
    db, settings = build_tiny_b(tiny_stages, tmp_path_factory)
    before = decision_digest(db)
    s1 = btl().draw_sample(db, settings)
    after_first = {t: count(db, t) for t in (*SAMPLE_TABLES, "audit_log")}
    again = btl().draw_sample(db, settings)
    after_second = {t: count(db, t) for t in (*SAMPLE_TABLES, "audit_log")}
    s300 = btl().draw_sample(db, settings, size=300)
    other, _ = build_tiny_b(tiny_stages, tmp_path_factory)
    twin = btl().draw_sample(other, settings)
    yield SimpleNamespace(
        db=db, settings=settings, before=before, after=decision_digest(db), s1=s1, again=again,
        s300=s300, twin=twin, after_first=after_first, after_second=after_second,
    )  # fmt: skip
    db.close()
    other.close()


def test_ac2_the_sample_of_50(state: SimpleNamespace) -> None:
    s = state.s1
    assert (s.run_id, s.seed, s.requested, s.population, s.size) == (1, 42, 50, 221, 50)
    assert (s.suspicious, s.not_suspicious, s.estimated_missed) == (3, 47, 13)
    assert s.prevalence_ci95 == (0.0206, 0.1622)
    assert s.reused is False
    ids = [m.golden_customer_id for m in s.members]
    assert ids == sorted(ids) and ids[:3] == FIRST_IDS
    suspicious = [m for m in s.members if m.label == "SUSPICIOUS"]
    assert [m.golden_customer_id for m in suspicious] == SUSPICIOUS_IDS
    assert all(m.typologies == ("rapid_movement",) for m in suspicious)
    alerted = set(
        query(state.db, "SELECT golden_customer_id FROM case_alerts WHERE run_id = 1")[
            "golden_customer_id"
        ]
    )
    assert not alerted & set(ids)


def test_ac2_storage_and_audit(state: SimpleNamespace) -> None:
    db, s = state.db, state.s1
    first = state.after_first
    assert (first["btl_samples"], first["btl_members"]) == (1, 50)
    every = audit_df(db, "decision = 'BTL_LABELLED'")
    labelled = every[[d["sample_id"] == s.sample_id for d in every["details"]]]
    assert len(labelled) == 50
    assert set(labelled["entity_type"]) == {"customer"}
    assert set(labelled["actor"]) == {"simulated_analyst"}
    assert set(labelled["version"]) == {"btl/v1"}
    reasons = {m.golden_customer_id: m.reason for m in s.members}
    assert dict(zip(labelled["entity_id"], labelled["reason"], strict=True)) == reasons
    sampled = audit_df(db, f"decision = 'BTL_SAMPLED' AND entity_id = '{s.sample_id}'")
    assert len(sampled) == 1
    reason = sampled["reason"].iloc[0]
    assert reason.startswith(
        "sampled 50 of 221 customer(s) with no alert in case run 1 (seed 42): "
        "3 in a suspicious scenario, estimated 13 missed"
    )
    assert reason.endswith("measurement only")
    assert sampled["details"].iloc[0]["population"] == 221


def test_ac2_a_second_call_reuses_the_sample(state: SimpleNamespace) -> None:
    a, b = state.s1, state.again
    assert b.sample_id == a.sample_id and b.members == a.members and b.reused is True
    assert state.after_second == state.after_first


def test_ac2_a_larger_size_is_a_new_sample(state: SimpleNamespace) -> None:
    s = state.s300
    assert s.sample_id != state.s1.sample_id
    assert (s.requested, s.size, s.suspicious) == (300, 221, 8)


def test_ac2_two_independent_databases_draw_the_same_members(state: SimpleNamespace) -> None:
    assert state.twin.members == state.s1.members


def test_ac2_no_decision_table_changes(state: SimpleNamespace) -> None:
    assert state.before == state.after


def test_ac2_errors_come_before_any_write(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    db, settings = build_tiny_b(tiny_stages, tmp_path_factory)
    try:
        db.execute("DELETE FROM ground_truth")
        with pytest.raises(prio_error(), match="no ground truth"):
            btl().draw_sample(db, settings)
        assert count(db, "btl_samples") == 0
    finally:
        db.close()
    bare = copy_tiny(tiny_stages, tmp_path_factory.mktemp("btl_bare") / "bare.duckdb")
    try:
        with pytest.raises(case_error(), match="run `aml cases build` first"):
            btl().draw_sample(bare, btl_settings())
        assert int(scalar(bare, "SELECT COUNT(*) FROM btl_samples")) == 0
    finally:
        bare.close()
