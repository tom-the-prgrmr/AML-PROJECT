"""AC7 for specs/case-consolidation.md: audit trail, full snapshots, deterministic reruns."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aml.common.db import Database, DuckDb

from .helpers import (
    CASE_C01_A,
    audit_cases,
    cases_current,
    count,
    duck_settings,
    js,
    load_minic,
    query,
    run_cases,
)


def test_ac7_first_run_audit_events(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    audit = audit_cases(minic)
    assert len(audit) == 6
    opened = audit[audit["decision"] == "CASE_OPENED"]
    assert len(opened) == 5
    assert set(opened["entity_type"]) == {"case"}
    assert set(opened["version"]) == {"cases/v1"}
    row = opened[opened["entity_id"] == CASE_C01_A].iloc[0]
    assert row["reason"] == cases_current(minic)[CASE_C01_A].reason
    assert row["details"]["alerts"] == 3
    assert row["details"]["sources"] == "NETWORK+RULE"
    assert len(row["details"]["item_keys"]) == 3

    done = audit[audit["decision"] == "CASE_RUN_COMPLETED"]
    assert len(done) == 1
    assert done.iloc[0]["entity_type"] == "case_run"
    assert done.iloc[0]["entity_id"] == "1"
    assert done.iloc[0]["details"]["cases"] == 5
    assert done.iloc[0]["details"]["items"] == 9


def test_ac7_second_run_is_a_clean_snapshot(minic: DuckDb) -> None:
    settings = duck_settings()
    first = run_cases(minic, settings)
    before = enrichments(minic, 1)
    second = run_cases(minic, settings)

    assert second.run_id == 2
    assert second.opened == 0
    for field in ("as_of", "items", "alerts", "suppressed", "active", "cases", "closed"):
        assert getattr(second, field) == getattr(first, field), field
    assert (second.reopened, second.graph_source) == (first.reopened, first.graph_source)

    new = audit_cases(minic, "entity_type = 'case_run' AND entity_id = '2'")
    assert list(new["decision"]) == ["CASE_RUN_COMPLETED"]
    assert len(audit_cases(minic)) == 7

    for table, rows in (("cases", 5), ("case_alerts", 9), ("case_enrichment", 30)):
        for run_id in (1, 2):
            assert count(minic, table, f"WHERE run_id = {run_id}") == rows, (table, run_id)
    assert enrichments(minic, 2) == before

    for view in ("cases_current", "case_alerts_current", "case_enrichment_current"):
        assert set(query(minic, f"SELECT run_id FROM {view}")["run_id"]) == {2}, view

    first_cases = query(
        minic, "SELECT case_id, status, alerts, reason FROM cases WHERE run_id = 1 ORDER BY 1"
    )
    second_cases = query(
        minic, "SELECT case_id, status, alerts, reason FROM cases WHERE run_id = 2 ORDER BY 1"
    )
    assert first_cases.equals(second_cases)


def enrichments(db: Database, run_id: int) -> dict[tuple[str, str], Any]:
    df = query(db, f"SELECT case_id, section, content FROM case_enrichment WHERE run_id = {run_id}")
    return {(r.case_id, r.section): js(r.content) for r in df.itertuples()}


def _snapshot(db: Database) -> dict[str, Any]:
    run = run_cases(db, duck_settings())
    ca = query(db, "SELECT * FROM case_alerts_current ORDER BY item_key, golden_customer_id")
    ca["details"] = [js(d) for d in ca["details"]]
    cases = query(db, "SELECT * FROM cases_current ORDER BY case_id").drop(columns=["run_id"])
    return {
        "run": run,
        "cases": cases.to_dict("records"),
        "case_alerts": ca.drop(columns=["run_id"]).to_dict("records"),
        "enrichment": enrichments(db, run.run_id),
    }


def test_ac7_physical_insert_order_does_not_change_the_result(tmp_path: Path) -> None:
    results = []
    for reverse in (False, True):
        with DuckDb(tmp_path / f"mini_{reverse}.duckdb") as db:
            load_minic(db, reverse=reverse)
            results.append(_snapshot(db))
    assert results[0] == results[1]
