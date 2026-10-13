"""AC3 for specs/case-prioritization.md: truth labels, case groups, simulated dispositions."""

from __future__ import annotations

import math
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from aml.common.db import DuckDb

from .helpers import (
    CASE_C01_A,
    CASE_C01_B,
    CASE_C03,
    CASE_C04,
    CASE_C05,
    audit_cases,
    case_error,
    count,
    duck_settings,
    load_minic,
    query,
    run_cases,
)
from .helpers import record_disposition as dispose
from .prio_helpers import (
    FRACTION,
    MINI_TRUTH,
    SIM_ACTOR,
    SIM_PREFIX,
    copy_tiny,
    insert_truth,
    labels_mod,
    minigt,
    prio_error,
)
from .supp_helpers import S2_KEY, STATE_ROWS, day, good_guys, item

AS_OF = "2026-06-30"
HALF = {FRACTION: "0.5"}
ALL = {FRACTION: "1.0"}


def _dispositions(db: DuckDb) -> Any:
    return query(
        db,
        "SELECT case_id, disposition, origin, actor, decided_on, run_id, reason "
        "FROM case_dispositions ORDER BY disposition_id",
    )


def test_ac3_truth_labels_of_mini_gt(duck: DuckDb) -> None:
    minigt(duck)
    labels = labels_mod().truth_labels(duck)
    assert set(labels) == {CASE_C01_A, CASE_C01_B, CASE_C03, CASE_C04, CASE_C05}

    a = labels[CASE_C01_A]
    assert (a.disposition, a.true_alerts, a.alerts) == ("SUSPICIOUS", 2, 3)
    assert tuple(a.typologies) == ("structuring",)
    assert a.case_id == CASE_C01_A
    assert a.reason == (
        "simulated from ground truth: 2 of 3 alert(s) match a suspicious scenario (structuring)"
    )

    b = labels[CASE_C01_B]  # R3 on A01 is true; the pair C02 x WL1 is not a true hit
    assert (b.disposition, b.true_alerts, b.alerts) == ("SUSPICIOUS", 1, 2)

    c = labels[CASE_C03]
    assert (c.disposition, c.true_alerts) == ("SUSPICIOUS", 2)
    assert tuple(c.typologies) == ("round_tripping",)

    d = labels[CASE_C04]  # A04 is only in a benign scenario; A01 and A03 are not G-C04's accounts
    assert (d.disposition, d.true_alerts, d.alerts) == ("FALSE_POSITIVE", 0, 1)
    assert d.reason == (
        "simulated from ground truth: none of the 1 alert(s) matches a suspicious scenario"
    )

    e = labels[CASE_C05]
    assert e.disposition == "SUSPICIOUS"
    assert tuple(e.typologies) == ("sanctions_hit",)


def test_ac3_case_groups_follow_shared_alerts(duck: DuckDb) -> None:
    minigt(duck)
    groups = labels_mod().case_groups(duck, 1)
    assert groups == {
        CASE_C01_A: CASE_C01_A,
        CASE_C03: CASE_C01_A,
        CASE_C04: CASE_C01_A,
        CASE_C01_B: CASE_C01_B,
        CASE_C05: CASE_C05,
    }
    assert len(set(groups.values())) == 3


def test_ac3_simulate_half_of_the_groups_with_the_seeded_order(duck: DuckDb) -> None:
    settings = minigt(duck, **HALF)
    # default_rng(42).permutation(3) == [2, 1, 0]: the last two groups of the sorted list
    assert list(np.random.default_rng(42).permutation(3)) == [2, 1, 0]
    labels = labels_mod()
    sim = labels.simulate_dispositions(duck, settings)
    assert asdict(sim) == {
        "run_id": 1,
        "groups": 3,
        "labelled_groups": 2,
        "labelled": 2,
        "suspicious": 2,
        "false_positive": 0,
        "held_out": 3,
        "skipped": 0,
    }
    rows = _dispositions(duck)
    assert sorted(rows["case_id"]) == [CASE_C01_B, CASE_C05]
    for row in rows.itertuples():
        assert row.origin == "SIMULATED"
        assert row.actor == SIM_ACTOR
        assert day(row.decided_on).isoformat() == AS_OF
        assert row.run_id == 1
        assert row.reason.startswith(SIM_PREFIX)
        assert row.disposition == "SUSPICIOUS"

    again = labels.simulate_dispositions(duck, settings)
    assert (again.labelled, again.skipped) == (0, 2)
    assert count(duck, "case_dispositions") == 2


def test_ac3_simulation_is_audited(duck: DuckDb) -> None:
    settings = minigt(duck, **HALF)
    labels = labels_mod()
    sim = labels.simulate_dispositions(duck, settings)
    labels.simulate_dispositions(duck, settings)

    each = audit_cases(duck, f"actor = '{SIM_ACTOR}' AND entity_type = 'case'")
    assert len(each) == 2
    assert sorted(each["entity_id"]) == [CASE_C01_B, CASE_C05]
    assert all(d["origin"] == "SIMULATED" for d in each["details"])

    runs = audit_cases(duck, "decision = 'DISPOSITIONS_SIMULATED'")
    assert len(runs) == 2  # one row per call, also when nothing was labelled
    assert set(runs["entity_type"]) == {"case_run"}
    first = runs["details"][0]
    for key, value in asdict(sim).items():
        assert first[key] == value, key


def test_ac3_a_human_decision_is_never_overwritten(duck: DuckDb) -> None:
    settings = minigt(duck, **ALL)
    dispose(duck, settings, CASE_C04, "SUSPICIOUS", reason="manual", actor="analyst01")
    sim = labels_mod().simulate_dispositions(duck, settings)
    assert (sim.labelled, sim.suspicious, sim.false_positive) == (4, 4, 0)
    assert (sim.skipped, sim.held_out) == (1, 0)
    current = query(
        duck,
        "SELECT actor, origin, disposition FROM case_dispositions_current "
        f"WHERE case_id = '{CASE_C04}'",
    )
    assert current.iloc[0].tolist() == ["analyst01", "HUMAN", "SUSPICIOUS"]
    assert count(duck, "case_dispositions", f"WHERE case_id = '{CASE_C04}'") == 1


def test_ac3_without_a_human_decision_c04_is_a_simulated_false_positive(duck: DuckDb) -> None:
    settings = minigt(duck, **ALL)
    sim = labels_mod().simulate_dispositions(duck, settings)
    assert (sim.groups, sim.labelled_groups) == (3, 3)
    assert (sim.labelled, sim.suspicious, sim.false_positive) == (5, 4, 1)
    assert (sim.skipped, sim.held_out) == (0, 0)
    row = query(
        duck,
        "SELECT disposition, origin, actor FROM case_dispositions_current "
        f"WHERE case_id = '{CASE_C04}'",
    ).iloc[0]
    assert row.tolist() == ["FALSE_POSITIVE", "SIMULATED", SIM_ACTOR]


def test_ac3_a_simulated_false_positive_feeds_the_good_guy_list(duck: DuckDb) -> None:
    """7b-supp: the simulated clearance of a screening-only case suppresses its pair next run."""
    load_minic(duck)
    insert_truth(duck, [r for r in MINI_TRUTH if r[3] == "account"])  # no true screening pair
    for entity_type, entity_id, fingerprint in STATE_ROWS:
        duck.execute(
            "INSERT INTO screening_state (entity_type, entity_id, fingerprint, run_id) "
            "VALUES (?, ?, ?, 1)",
            [entity_type, entity_id, fingerprint],
        )
    settings = duck_settings(**ALL)
    run_cases(duck, settings)
    sim = labels_mod().simulate_dispositions(duck, settings)
    assert (sim.suspicious, sim.false_positive) == (3, 2)

    rows = good_guys(duck)
    assert len(rows) == 1
    assert (rows.iloc[0]["case_id"], rows.iloc[0]["actor"]) == (CASE_C05, SIM_ACTOR)
    run2 = run_cases(duck, settings)
    assert (run2.suppressed, run2.cases) == (1, 4)
    assert item(duck, S2_KEY)["status"] == "SUPPRESSED"


def test_ac3_tiny_every_case_is_suspicious_with_all_groups(tiny_cases: DuckDb) -> None:
    settings = duck_settings(**ALL)
    run_cases(tiny_cases, settings)
    sim = labels_mod().simulate_dispositions(tiny_cases, settings)
    assert sim.groups == 18
    assert (sim.labelled, sim.suspicious, sim.false_positive) == (52, 52, 0)
    assert sim.held_out == 0


def _simulate_tiny(db: DuckDb) -> tuple[Any, set[str], dict[str, str]]:
    settings = duck_settings(**{FRACTION: "0.7"})
    run_cases(db, settings)
    sim = labels_mod().simulate_dispositions(db, settings)
    disposed = set(query(db, "SELECT case_id FROM case_dispositions")["case_id"])
    return sim, disposed, labels_mod().case_groups(db, sim.run_id)


def test_ac3_tiny_seventy_percent_of_the_groups(
    tiny_cases: DuckDb, tiny_stages: dict[str, Path], tmp_path: Path
) -> None:
    sim, disposed, groups = _simulate_tiny(tiny_cases)
    assert sim.groups == 18
    assert sim.labelled_groups == 13 == math.ceil(0.7 * 18)
    assert sim.labelled + sim.held_out == 52
    assert sim.labelled == len(disposed)

    members: dict[str, set[str]] = {}
    for case_id, group_id in groups.items():
        members.setdefault(group_id, set()).add(case_id)
    for group_id, cases in members.items():  # a group is labelled whole or not at all
        assert cases <= disposed or not (cases & disposed), group_id

    order = np.random.default_rng(42).permutation(18)  # groups sorted by id, then permuted
    chosen = [sorted(members)[i] for i in order[:13]]
    assert disposed == set().union(*(members[g] for g in chosen))

    with copy_tiny(tiny_stages, tmp_path / "second.duckdb") as other:
        _, disposed_again, _ = _simulate_tiny(other)
    assert disposed_again == disposed  # same case ids, same seed: same assignment


def test_ac3_empty_ground_truth_is_refused_and_nothing_is_written(duck: DuckDb) -> None:
    load_minic(duck)  # no ground_truth rows
    settings = duck_settings()
    run_cases(duck, settings)
    with pytest.raises(prio_error(), match="no ground truth"):
        labels_mod().simulate_dispositions(duck, settings)
    assert count(duck, "case_dispositions") == 0
    assert audit_cases(duck, "decision = 'DISPOSITIONS_SIMULATED'").empty


def test_ac3_no_case_run_yet_is_a_case_error(duck: DuckDb) -> None:
    load_minic(duck)
    insert_truth(duck)
    with pytest.raises(case_error(), match=re.escape("run `aml cases build` first")):
        labels_mod().simulate_dispositions(duck, duck_settings())
    assert count(duck, "case_dispositions") == 0
