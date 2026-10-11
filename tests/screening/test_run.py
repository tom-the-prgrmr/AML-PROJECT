"""AC6-AC7 for specs/screening-tiers-eval.md: `run_screening` on TINY, audit and supersession."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb
from tests.dba.conftest import audit_rows

from .helpers import mod
from .helpers_3b import AS_OF, TRUE_PAIRS, duck_settings, load_tiny_duck, query, results_row


def _run(db: DuckDb, settings: Settings) -> Any:
    return mod("aml.screening.runner").run_screening(db, settings)


@pytest.fixture
def tiny(tiny_parquet: Path, tmp_path: Path) -> Iterator[tuple[DuckDb, Settings]]:
    db = load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb")
    yield db, duck_settings()
    db.close()


def test_ac6_first_run_counts_and_alert_pairs(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    run = _run(db, settings)
    assert (run.run_id, run.mode, run.as_of) == (1, "FULL", AS_OF)
    assert (run.customers_screened, run.entries_screened) == (300, 200)
    assert (run.alerts, run.reviews, run.superseded) == (5, 0, 0)
    assert run.auto_cleared >= 1
    n_rows = int(db.query_df("SELECT COUNT(*) FROM screening_results").iloc[0, 0])
    assert run.recorded == run.alerts + run.reviews + run.auto_cleared == n_rows
    assert run.recorded <= run.candidate_pairs <= 600

    alerts = query(db, "SELECT * FROM screening_results WHERE decision = 'ALERT'")
    assert set(zip(alerts["cif"], alerts["entry_id"], strict=True)) == TRUE_PAIRS
    assert mod("aml.screening.evaluate").truth_pairs(db) == TRUE_PAIRS
    assert list(alerts["name_score"].round(2)) == [100.0] * 5
    assert list(alerts["final_score"].round(2)) == [100.0] * 5


def test_ac6_specific_rows(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    _run(db, settings)
    aka = results_row(db, "CIF00000032", "WL000084")
    assert (aka["matched_name"], aka["matched_name_type"]) == ("DANG ANH ANH", "AKA")
    primary = results_row(db, "CIF00000104", "WL000158")
    assert (primary["matched_name"], primary["matched_name_type"]) == ("HUYNH XUAN SON", "PRIMARY")
    assert pd.isna(primary["dob_gap_years"])
    cleared = results_row(db, "CIF00000214", "WL000099")
    assert cleared["decision"] == "AUTO_CLEARED"
    assert cleared["reason"].startswith("DOB mismatch > 5y")
    assert cleared["matched_name"] == "LE THI NHUNG"
    assert round(float(cleared["fuzzy_score"]), 2) == 96.66
    assert round(float(cleared["name_score"]), 2) == 78.09
    assert int(cleared["dob_gap_years"]) == 38


def test_ac6_traps_never_alert_and_rows_are_well_formed(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    _run(db, settings)
    traps = query(db, "SELECT entity_id FROM ground_truth WHERE typology = 'screening_trap'")[
        "entity_id"
    ]
    assert len(traps) == 6
    res = query(db, "SELECT * FROM screening_results")
    flagged_traps = res[
        res["entry_id"].isin(set(traps)) & res["decision"].isin(["ALERT", "REVIEW"])
    ]
    assert flagged_traps.empty
    assert (res["reason"].fillna("").str.len() > 0).all()
    assert (res["fuzzy_score"] >= 75).all()
    assert res["superseded_by"].isna().all()
    assert set(res["matched_name_type"]) <= {"PRIMARY", "AKA", "TRANSLITERATION", "REORDERED"}


def test_ac6_screening_runs_row(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    run = _run(db, settings)
    runs = query(db, "SELECT * FROM screening_runs")
    assert len(runs) == 1
    r = runs.iloc[0]
    for field in (
        "run_id", "customers_screened", "entries_screened", "candidate_pairs",
        "recorded", "alerts", "reviews", "auto_cleared", "superseded",
    ):  # fmt: skip
        assert int(r[field]) == getattr(run, field), field
    assert r["mode"] == "FULL"
    assert str(r["as_of"])[:10] == "2026-06-30"
    assert r["version"] == "screening/v1"
    assert re.fullmatch(r"[0-9a-f]{16}", r["config_hash"])


def test_ac7_audit_rows_for_first_run(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    run = _run(db, settings)
    matches = audit_rows(db, "module = 'screening' AND entity_type = 'screening_match'")
    assert len(matches) == run.recorded
    counts = matches["decision"].value_counts().to_dict()
    assert counts.get("ALERT", 0) == run.alerts
    assert counts.get("REVIEW", 0) == run.reviews
    assert counts.get("AUTO_CLEARED", 0) == run.auto_cleared

    row = matches[matches["entity_id"] == "CIF00000104:WL000158"].iloc[0]
    assert row["decision"] == "ALERT"
    d = row["details"]
    assert (d["run_id"], d["name_score"], d["matched_name"]) == (1, 100.0, "HUYNH XUAN SON")
    full = query(
        db,
        "SELECT version FROM audit_log WHERE entity_id = 'CIF00000104:WL000158' "
        "AND module = 'screening'",
    )
    assert list(full["version"]) == ["screening/v1"]

    cleared = matches[matches["entity_id"] == "CIF00000214:WL000099"].iloc[0]
    assert cleared["decision"] == "AUTO_CLEARED"
    reason = query(
        db,
        "SELECT reason FROM audit_log WHERE module = 'screening' "
        "AND entity_id = 'CIF00000214:WL000099'",
    )["reason"].iloc[0]
    assert reason == results_row(db, "CIF00000214", "WL000099")["reason"]

    summary = audit_rows(db, "module = 'screening' AND entity_type = 'screening_run'")
    assert len(summary) == 1
    s = summary.iloc[0]
    assert (s["entity_id"], s["decision"]) == ("1", "SCREENING_RUN_COMPLETED")
    assert (s["details"]["mode"], s["details"]["alerts"], s["details"]["reviews"]) == ("FULL", 5, 0)


def test_ac7_second_run_supersedes_first(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    first = _run(db, settings)
    audit_before = int(
        db.query_df("SELECT COUNT(*) FROM audit_log WHERE module = 'screening'").iloc[0, 0]
    )
    second = _run(db, settings)
    assert second.run_id == 2
    assert second.superseded == first.recorded

    old = query(db, "SELECT superseded_by FROM screening_results WHERE run_id = 1")
    assert len(old) == first.recorded
    assert (old["superseded_by"] == 2).all()
    cur = query(db, "SELECT DISTINCT run_id FROM screening_current")
    assert list(cur["run_id"]) == [2]

    cols = "cif, entry_id, decision, reason, name_score, final_score"
    a = query(db, f"SELECT {cols} FROM screening_results WHERE run_id = 1 ORDER BY 1, 2")
    b = query(db, f"SELECT {cols} FROM screening_results WHERE run_id = 2 ORDER BY 1, 2")
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))

    audit_after = int(
        db.query_df("SELECT COUNT(*) FROM audit_log WHERE module = 'screening'").iloc[0, 0]
    )
    assert audit_after - audit_before == second.recorded + 1
