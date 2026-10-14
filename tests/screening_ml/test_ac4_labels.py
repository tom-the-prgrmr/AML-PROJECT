"""AC4 for specs/screening-ml.md: simulated labels, never a review of a person."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from aml.common.db import DuckDb
from aml.screening.evaluate import truth_pairs
from aml.screening.review import latest_reviews, record_review

from .helpers import audit_df, mod, query, scalar, settings_with, snapshot


def _labels() -> Any:
    return mod("aml.screening.ml.labels")


def _screening_audit_rows(db: DuckDb) -> int:
    return int(scalar(db, "SELECT COUNT(*) FROM audit_log WHERE module = 'screening'"))


def test_ac4_default_fraction(tiny_s: DuckDb) -> None:
    labels = _labels()
    results = snapshot(tiny_s, "screening_results", "run_id, cif, entry_id")
    before = _screening_audit_rows(tiny_s)
    sim = labels.simulate_labels(tiny_s, settings_with())
    assert sim == labels.LabelSimulation(
        groups=34, labelled_groups=24, labelled=39, true_match=4, false_match=35,
        held_out=16, skipped=0,
    )  # fmt: skip
    rows = query(tiny_s, "SELECT * FROM screening_ml_labels")
    assert len(rows) == 39
    assert set(rows["origin"]) == {"SIMULATED"}
    assert set(rows["actor"]) == {"simulated_analyst"}
    assert rows["reason"].str.startswith("simulated from ground truth:").all()
    cur = query(tiny_s, "SELECT cif, entry_id FROM screening_current")
    labelled = set(zip(rows["cif"], rows["entry_id"], strict=True))
    for _, group in cur.groupby("entry_id"):
        flags = {(c, e) in labelled for c, e in zip(group["cif"], group["entry_id"], strict=True)}
        assert len(flags) == 1

    again = labels.simulate_labels(tiny_s, settings_with())
    assert (again.labelled, again.skipped) == (0, 39)
    assert scalar(tiny_s, "SELECT COUNT(*) FROM screening_ml_labels") == 39

    per = audit_df(tiny_s, "module = 'screening_ml' AND entity_type = 'screening_label'")
    assert len(per) == 39
    assert set(per["decision"]) == {"SIMULATED_LABEL"}
    assert set(per["actor"]) == {"simulated_analyst"}
    assert {d["origin"] for d in per["details"]} == {"SIMULATED"}
    assert [d["label"] for d in per["details"]].count("TRUE_MATCH") == 4
    assert set(d["label"] for d in per["details"]) <= {"TRUE_MATCH", "FALSE_MATCH"}
    assert (
        scalar(
            tiny_s,
            "SELECT COUNT(*) FROM audit_log WHERE module = 'screening_ml' "
            "AND decision IN ('TRUE_MATCH', 'FALSE_MATCH')",
        )
        == 0
    )
    assert scalar(tiny_s, "SELECT COUNT(*) FROM audit_log WHERE decision = 'LABELS_SIMULATED'") == 2
    assert latest_reviews(tiny_s) == {}
    assert _screening_audit_rows(tiny_s) == before
    assert snapshot(tiny_s, "screening_results", "run_id, cif, entry_id") == results


def test_ac4_same_pairs_on_independent_databases(
    make_tiny_s: Callable[[], DuckDb],
) -> None:
    pair_sets = []
    for _ in range(2):
        db = make_tiny_s()
        _labels().simulate_labels(db, settings_with())
        pair_sets.append(
            set(map(tuple, query(db, "SELECT cif, entry_id FROM screening_ml_labels").to_numpy()))
        )
    assert pair_sets[0] == pair_sets[1]


def test_ac4_fraction_one_labels_everything_from_the_truth(tiny_s: DuckDb) -> None:
    sim = _labels().simulate_labels(
        tiny_s, settings_with(AML__ML__SCREENING__SIMULATE_FRACTION="1.0")
    )
    assert (sim.labelled, sim.true_match, sim.false_match, sim.held_out) == (55, 5, 50, 0)
    rows = query(tiny_s, "SELECT cif, entry_id FROM screening_ml_labels WHERE label = 'TRUE_MATCH'")
    assert set(zip(rows["cif"], rows["entry_id"], strict=True)) == set(truth_pairs(tiny_s))


def test_ac4_a_human_review_is_not_overwritten(tiny_s: DuckDb) -> None:
    s = settings_with(AML__ML__SCREENING__SIMULATE_FRACTION="1.0")
    record_review(
        tiny_s, s, "CIF00000214", "WL000099", "TRUE_MATCH", reason="manual", actor="analyst01"
    )
    sim = _labels().simulate_labels(tiny_s, s)
    assert (sim.labelled, sim.skipped) == (54, 1)
    assert (
        scalar(
            tiny_s,
            "SELECT COUNT(*) FROM screening_ml_labels "
            "WHERE cif = 'CIF00000214' AND entry_id = 'WL000099'",
        )
        == 0
    )
    df = _labels().training_labels(tiny_s, s)
    assert len(df) == 55
    row = df.loc[("CIF00000214", "WL000099")]
    assert (row["label"], row["origin"]) == (1, "HUMAN")
    assert int(df["label"].sum()) == 6
    off = settings_with(
        AML__ML__SCREENING__SIMULATE_FRACTION="1.0", AML__ML__SCREENING__USE_HUMAN_REVIEWS="false"
    )
    df_off = _labels().training_labels(tiny_s, off)
    assert len(df_off) == 54
    assert ("CIF00000214", "WL000099") not in df_off.index


def test_ac4_empty_ground_truth_writes_nothing(tiny_s: DuckDb) -> None:
    tiny_s.execute("DELETE FROM ground_truth")
    with pytest.raises(mod("aml.screening.ml.model").ScreeningMlError, match="no ground truth"):
        _labels().simulate_labels(tiny_s, settings_with())
    assert scalar(tiny_s, "SELECT COUNT(*) FROM screening_ml_labels") == 0
    assert scalar(tiny_s, "SELECT COUNT(*) FROM audit_log WHERE module = 'screening_ml'") == 0


def test_ac4_without_screening_fails(tiny_loaded: DuckDb) -> None:
    with pytest.raises(
        mod("aml.screening.ml.model").ScreeningMlError, match="run `aml screen` first"
    ):
        _labels().simulate_labels(tiny_loaded, settings_with())
    assert scalar(tiny_loaded, "SELECT COUNT(*) FROM screening_ml_labels") == 0
