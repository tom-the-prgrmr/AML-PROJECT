"""AC5-AC9 for specs/screening-oracle-incremental.md: fingerprints, incremental run, audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from aml.common.config import load_settings
from tests.dba.conftest import audit_rows

from .helpers import mod
from .helpers_3c import (
    apply_delta,
    audit_count,
    count,
    current_set,
    duck_settings,
    full_screen_tiny,
    load_tiny_duck,
    query,
    run_full,
    run_inc,
    token_stats_from,
)


def test_ac5_first_incremental_is_full_second_is_empty(tiny_parquet: Path, tmp_path: Path) -> None:
    db = load_tiny_duck(tiny_parquet, tmp_path / "t.duckdb")
    settings = duck_settings()
    first = run_inc(db, settings)
    assert (first.mode, first.run_id, first.alerts) == ("FULL", 1, 5)
    st = query(db, "SELECT entity_type, COUNT(*) AS n FROM screening_state GROUP BY 1")
    assert dict(zip(st["entity_type"], st["n"], strict=True)) == {
        "customer": 300,
        "watchlist_entry": 200,
    }
    ts = query(db, "SELECT * FROM screening_token_stats")
    assert len(ts) == 85
    assert set(ts["n_names"]) == {300}
    assert int(ts[ts["token"] == "NGUYEN"].iloc[0]["doc_freq"]) == 115

    before = current_set(db)
    audit_before = audit_count(db)
    second = run_inc(db, settings)
    assert second.mode == "INCREMENTAL" and second.run_id == 2
    assert (second.customers_screened, second.entries_screened) == (0, 0)
    assert (second.candidate_pairs, second.recorded, second.superseded) == (0, 0, 0)
    assert current_set(db) == before
    assert set(query(db, "SELECT run_id FROM screening_current")["run_id"]) == {1}
    assert audit_count(db) == audit_before + 1
    rows = audit_rows(db, "module = 'screening' AND entity_id = '2'")
    assert len(rows) == 1 and rows.iloc[0]["entity_type"] == "screening_run"
    assert rows.iloc[0]["details"]["mode"] == "INCREMENTAL"
    db.close()


def test_ac6_detect_delta_uses_fingerprints_and_is_read_only(
    tiny_parquet: Path, tmp_path: Path
) -> None:
    db, settings = full_screen_tiny(tiny_parquet, tmp_path / "t.duckdb")
    inc = mod("aml.screening.incremental")
    apply_delta(db)
    db.execute("UPDATE customers SET phone = '0900000000' WHERE cif = 'CIF00000001'")
    db.execute("UPDATE watchlist SET program = 'CYBER' WHERE entry_id = 'WL000001'")
    snap = (
        audit_count(db),
        count(db, "SELECT COUNT(*) FROM screening_state"),
        count(db, "SELECT COUNT(*) FROM screening_runs"),
    )
    d = inc.detect_delta(db, settings)
    assert d.customers_changed == frozenset({"CIF00000214"})
    assert d.customers_removed == frozenset()
    assert d.entries_changed == frozenset({"WL900001"})
    assert d.entries_removed == frozenset({"WL000158"})

    db.execute(
        "INSERT INTO watchlist_alias (alias_id, entry_id, alias_name, alias_type) "
        "VALUES ('WA9000001', 'WL000001', 'TEST ALIAS', 'AKA')"
    )
    d2 = inc.detect_delta(db, settings)
    assert d2.entries_changed == frozenset({"WL900001", "WL000001"})
    assert snap == (
        audit_count(db),
        count(db, "SELECT COUNT(*) FROM screening_state"),
        count(db, "SELECT COUNT(*) FROM screening_runs"),
    )
    db.close()


def test_ac7_incremental_after_delta(tiny_parquet: Path, tmp_path: Path) -> None:
    db, settings = full_screen_tiny(tiny_parquet, tmp_path / "t.duckdb")
    apply_delta(db)
    run = run_inc(db, settings)
    assert (run.run_id, run.mode) == (2, "INCREMENTAL")
    assert (run.customers_screened, run.entries_screened) == (1, 1)
    assert (run.recorded, run.alerts, run.reviews, run.auto_cleared) == (2, 1, 1, 0)
    assert run.superseded == 2
    assert run.candidate_pairs <= 20

    new = query(db, "SELECT * FROM screening_results WHERE run_id = 2")
    assert len(new) == 2
    r = new[(new["cif"] == "CIF00000214") & (new["entry_id"] == "WL000099")].iloc[0]
    assert r["decision"] == "REVIEW"
    assert round(float(r["name_score"]), 2) == 78.09
    assert round(float(r["final_score"]), 2) == 78.09
    assert int(r["dob_gap_years"]) == 0
    a = new[(new["cif"] == "CIF00000002") & (new["entry_id"] == "WL900001")].iloc[0]
    assert a["decision"] == "ALERT"
    assert round(float(a["name_score"]), 2) == 100.0
    assert a["matched_name"] == "NGO THI LAN"

    old = query(db, "SELECT cif, entry_id, superseded_by FROM screening_results WHERE run_id = 1")
    sup = old[old["superseded_by"].notna()]
    assert set(zip(sup["cif"], sup["entry_id"], strict=True)) == {
        ("CIF00000214", "WL000099"),
        ("CIF00000104", "WL000158"),
    }
    assert (sup["superseded_by"] == 2).all()

    cur = query(db, "SELECT * FROM screening_current")
    counts = cur["decision"].value_counts().to_dict()  # AUTO_CLEARED rows stay current too
    assert (counts.get("ALERT"), counts.get("REVIEW")) == (5, 1)
    assert "WL000158" not in set(cur["entry_id"])

    state = query(db, "SELECT entity_type, entity_id FROM screening_state")
    ids = set(state["entity_id"])
    assert "WL000158" not in ids and "WL900001" in ids
    d = mod("aml.screening.incremental").detect_delta(db, settings)
    assert (d.customers_changed, d.customers_removed) == (frozenset(), frozenset())
    assert (d.entries_changed, d.entries_removed) == (frozenset(), frozenset())
    db.close()


def test_ac8_incremental_equals_full_with_frozen_idf(tiny_parquet: Path, tmp_path: Path) -> None:
    a, settings = full_screen_tiny(tiny_parquet, tmp_path / "a.duckdb")
    apply_delta(a)
    inc = run_inc(a, settings)
    stats = token_stats_from(a)

    b = load_tiny_duck(tiny_parquet, tmp_path / "b.duckdb")
    apply_delta(b)
    full = run_full(b, settings, token_stats=stats)
    assert current_set(a) == current_set(b)
    assert inc.candidate_pairs > 0
    assert full.candidate_pairs >= 10 * inc.candidate_pairs
    a.close()
    b.close()


def test_ac9_audit_events_and_config_change_refused(tiny_parquet: Path, tmp_path: Path) -> None:
    db, settings = full_screen_tiny(tiny_parquet, tmp_path / "t.duckdb")
    apply_delta(db)
    last = count(db, "SELECT MAX(audit_id) FROM audit_log")
    run_inc(db, settings)
    new = audit_rows(db, f"module = 'screening' AND audit_id > {last}")
    assert len(new) == 4
    by_id = {(r.entity_type, r.entity_id): r for r in new.itertuples()}
    rev = by_id[("screening_match", "CIF00000214:WL000099")]
    alr = by_id[("screening_match", "CIF00000002:WL900001")]
    assert (rev.decision, alr.decision) == ("REVIEW", "ALERT")
    assert rev.details["run_id"] == 2 and alr.details["run_id"] == 2
    wd = by_id[("screening_match", "CIF00000104:WL000158")]
    assert wd.decision == "WITHDRAWN"
    assert wd.details["previous_decision"] == "ALERT"
    summary = by_id[("screening_run", "2")]
    d = summary.details
    assert d["mode"] == "INCREMENTAL"
    assert (d["customers_changed"], d["entries_changed"]) == (1, 1)
    assert (d["entries_removed"], d["customers_removed"]) == (1, 0)
    withdrawn = new[new["decision"] == "WITHDRAWN"]
    assert "CIF00000214:WL000099" not in set(withdrawn["entity_id"])
    reason = query(
        db,
        "SELECT reason FROM audit_log WHERE decision = 'WITHDRAWN' "
        "AND entity_id = 'CIF00000104:WL000158'",
    )["reason"].iloc[0]
    assert "watchlist entry removed" in reason

    strict = load_settings(
        environ={"DB_BACKEND": "duckdb", "AML__SCREENING__ALERT_THRESHOLD": "85"}
    )
    sizes = [
        count(db, f"SELECT COUNT(*) FROM {t}")
        for t in ("screening_runs", "screening_results", "audit_log")
    ]
    err = mod("aml.screening.runner").ScreeningError
    with pytest.raises(err, match="full screen required"):
        run_inc(db, strict)
    assert sizes == [
        count(db, f"SELECT COUNT(*) FROM {t}")
        for t in ("screening_runs", "screening_results", "audit_log")
    ]
    db.close()
