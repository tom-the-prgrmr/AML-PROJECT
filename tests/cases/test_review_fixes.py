"""Review fixes for Phase 7a: published runs only, `--decided-on`, case id guard, CASE_UPDATED."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import (
    CASE_C01_A,
    MINI_CASES,
    TINY_CASE,
    add_r5,
    audit_cases,
    case_error,
    cli,
    count,
    duck_settings,
    load_case,
    query,
    record_disposition,
    run_cases,
)

UseStage = Callable[[str], Path]


def _orphan_copy(db: DuckDb, run_id: int) -> None:
    """Copy the rows of run 1 of `cases` / `case_alerts` to a run that has no `case_runs` row."""
    for table in ("cases", "case_alerts"):
        db.execute(f"INSERT INTO {table} SELECT * REPLACE ({run_id} AS run_id) FROM {table}")


def test_disposition_ignores_an_unpublished_run(minic: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minic, settings)
    _orphan_copy(minic, 99)
    record_disposition(
        minic, settings, CASE_C01_A, "FALSE_POSITIVE", reason="explained", actor="analyst01"
    )
    assert query(minic, "SELECT run_id FROM case_dispositions")["run_id"].tolist() == [1]
    second = run_cases(minic, settings)
    assert second.run_id == 100  # the orphan id is never reused
    assert (second.opened, second.reopened) == (0, 0)


def test_first_published_run_still_counts_opened(minic: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minic, settings)
    minic.execute("DELETE FROM case_runs WHERE run_id = 1")  # as if the run died before this row
    second = run_cases(minic, settings)
    assert second.run_id == 2
    assert second.opened == len(MINI_CASES)


def test_decided_on_option(cli_db: UseStage) -> None:
    path = cli_db("sources")
    assert cli("cases", "build").exit_code == 0
    args = ("cases", "dispose", TINY_CASE, "--disposition", "SUSPICIOUS", "--reason", "r")
    ok = cli(*args, "--actor", "analyst01", "--decided-on", "2026-06-15")
    assert ok.exit_code == 0, ok.output
    bad = cli(*args, "--actor", "analyst01", "--decided-on", "2026-13-45")
    assert bad.exit_code == 2, bad.output
    with DuckDb(path) as db:
        assert count(db, "case_dispositions") == 1
        decided = query(db, "SELECT decided_on FROM case_dispositions")["decided_on"].iloc[0]
        assert pd.Timestamp(decided).date() == date(2026, 6, 15)


def test_injected_case_id_is_rejected(minic: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minic, settings)
    evil = "C-C01-20260302' OR '1'='1"
    with pytest.raises(case_error()):
        load_case(minic, evil)
    with pytest.raises(case_error()):
        record_disposition(minic, settings, evil, "SUSPICIOUS", reason="x", actor="analyst01")
    assert count(minic, "case_dispositions") == 0


def test_changed_item_set_gives_one_case_updated(minic: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minic, settings)
    add_r5(minic)
    run_cases(minic, settings)
    updated = audit_cases(minic, "decision = 'CASE_UPDATED'")
    assert updated["entity_id"].tolist() == [CASE_C01_A]
