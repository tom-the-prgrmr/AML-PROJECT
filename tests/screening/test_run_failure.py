"""A screening run that fails while writing must not lose the alerts of the previous run."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aml.screening.runner import run_screening

from .helpers_3b import duck_settings, load_tiny_duck, query


def _current_alerts(db: object) -> int:
    return len(query(db, "SELECT * FROM screening_current WHERE decision = 'ALERT'"))


def test_failed_result_insert_keeps_previous_run_current(
    tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb")
    settings = duck_settings()
    try:
        assert run_screening(db, settings).run_id == 1
        real_insert = db.insert_df

        def failing_insert(table: str, df: pd.DataFrame) -> int:
            if table == "screening_results":
                raise RuntimeError("disk full")
            return real_insert(table, df)

        monkeypatch.setattr(db, "insert_df", failing_insert)
        with pytest.raises(RuntimeError, match="disk full"):
            run_screening(db, settings)
        assert _current_alerts(db) == 5

        monkeypatch.undo()
        assert run_screening(db, settings).run_id == 2
        assert _current_alerts(db) == 5
    finally:
        db.close()


def test_run_after_missing_run_row_gets_a_fresh_run_id(
    tiny_parquet: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb")
    settings = duck_settings()
    try:
        real_insert = db.insert_df

        def failing_insert(table: str, df: pd.DataFrame) -> int:
            if table == "screening_runs":
                raise RuntimeError("connection lost")
            return real_insert(table, df)

        monkeypatch.setattr(db, "insert_df", failing_insert)
        with pytest.raises(RuntimeError, match="connection lost"):
            run_screening(db, settings)
        assert _current_alerts(db) == 5

        monkeypatch.undo()
        assert run_screening(db, settings).run_id == 2
        assert _current_alerts(db) == 5
    finally:
        db.close()
