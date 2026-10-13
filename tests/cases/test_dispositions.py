"""AC6 for specs/case-consolidation.md: `record_disposition`, CLOSED / REOPENED, audit."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import (
    CASE_C01_A,
    CASE_C01_B,
    add_r5,
    audit_cases,
    case_error,
    cases_current,
    count,
    duck_settings,
    enrichment,
    load_case,
    query,
    record_disposition,
    run_cases,
)

REASON = "cash deposits explained by a property sale"


def _dispose(db: DuckDb, disposition: str = "FALSE_POSITIVE", actor: str = "analyst01") -> int:
    return record_disposition(
        db,
        duck_settings(),
        CASE_C01_A,
        disposition,
        reason=REASON,
        actor=actor,
        decided_on=date(2026, 6, 30),
    )


def test_ac6_disposition_row_and_audit(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    assert _dispose(minic) == 1
    row = query(minic, "SELECT * FROM case_dispositions").iloc[0]
    assert len(query(minic, "SELECT * FROM case_dispositions")) == 1
    assert row["case_id"] == CASE_C01_A
    assert row["run_id"] == 1
    assert row["disposition"] == "FALSE_POSITIVE"
    assert row["actor"] == "analyst01"
    assert row["origin"] == "HUMAN"
    assert pd.Timestamp(row["decided_on"]).date() == date(2026, 6, 30)

    audit = audit_cases(minic, "entity_type = 'case' AND decision = 'FALSE_POSITIVE'")
    assert len(audit) == 1
    a = audit.iloc[0]
    assert a["entity_id"] == CASE_C01_A
    assert a["actor"] == "analyst01"
    assert a["reason"] == REASON
    assert a["details"]["disposition_id"] == 1


def test_ac6_a_disposition_never_updates_cases_rows(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    _dispose(minic)
    status = query(minic, f"SELECT status FROM cases WHERE run_id = 1 AND case_id = '{CASE_C01_A}'")
    assert list(status["status"]) == ["OPEN"]


def test_ac6_next_run_closes_the_case(minic: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minic, settings)
    _dispose(minic)
    run = run_cases(minic, settings)
    assert (run.cases, run.opened, run.reopened, run.closed) == (5, 0, 0, 1)
    got = cases_current(minic)
    assert got[CASE_C01_A].status == "CLOSED"
    assert {c: r.status for c, r in got.items() if c != CASE_C01_A} == {
        c: "OPEN" for c in got if c != CASE_C01_A
    }
    prior = enrichment(minic, CASE_C01_B)["history"]["prior_cases"][0]
    assert prior["disposition"] == "FALSE_POSITIVE"
    assert prior["decided_on"] == "2026-06-30"
    assert load_case(minic, CASE_C01_A).disposition.actor == "analyst01"


def test_ac6_new_alert_reopens_and_second_decision_closes_again(minic: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minic, settings)
    _dispose(minic)
    run_cases(minic, settings)
    add_r5(minic)

    run3 = run_cases(minic, settings)
    row = cases_current(minic)[CASE_C01_A]
    assert row.alerts == 4
    assert row.status == "REOPENED"
    assert (run3.reopened, run3.closed) == (1, 0)
    reopened = audit_cases(minic, "decision = 'CASE_REOPENED'")
    assert list(reopened["entity_id"]) == [CASE_C01_A]

    assert _dispose(minic, "SUSPICIOUS", "analyst02") == 2
    run_cases(minic, settings)
    assert cases_current(minic)[CASE_C01_A].status == "CLOSED"
    current = query(
        minic, f"SELECT * FROM case_dispositions_current WHERE case_id = '{CASE_C01_A}'"
    )
    assert list(current["disposition_id"]) == [2]
    # nothing of run 1 was changed or removed along the way
    assert count(minic, "cases", "WHERE run_id = 1") == 5


def test_ac6_unknown_case_is_rejected(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    with pytest.raises(case_error(), match="unknown case_id"):
        record_disposition(
            minic, duck_settings(), "C-NOPE-20260101", "SUSPICIOUS", reason="x", actor="a"
        )
    assert count(minic, "case_dispositions") == 0


def test_ac6_invalid_disposition_is_rejected(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    with pytest.raises(ValueError):
        _dispose(minic, "CLOSED")
    assert count(minic, "case_dispositions") == 0


def test_ac6_empty_reason_is_rejected(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    with pytest.raises(ValueError):
        record_disposition(
            minic, duck_settings(), CASE_C01_A, "SUSPICIOUS", reason="", actor="analyst01"
        )
    assert count(minic, "case_dispositions") == 0


def test_ac6_system_actor_cannot_decide(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    with pytest.raises(case_error(), match="a disposition needs a human actor"):
        _dispose(minic, "SUSPICIOUS", "system")
    assert count(minic, "case_dispositions") == 0
