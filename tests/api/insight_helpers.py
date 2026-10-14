"""Shared builders for the Phase 9c tests (specs/ui-mock-pages.md).

Fixtures named in the spec: SCORED, MINI-GT, MINI-S, FAKES, ROWS. Product modules that do not
exist yet (``aml.metrics``, ``aml.assistant.feedback``, new routers) are imported lazily by the
tests, never here, so a missing module fails the test that needs it and not the collection.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.db import Database
from tests.assistant.an_helpers import K3, LLM, R4
from tests.cases.prio_helpers import minigt
from tests.cases.supp_helpers import dispose, load_minis

from .helpers import ROOT, api_settings, count, mod

V1 = "/api/v1"
C1 = "C-C01-20260302"
C5 = "C-C05-20260630"
NOPE = "C-NOPE-20260101"
Q = "  Tài khoản A01 nhận tiền gì?  "
ANSWER_ID = "ans-9504e4efe5dd"
SCREENING_EVAL_CSV = ROOT / "results" / "phase3" / "screening_eval.csv"

# (case_id, score, queue_rank, top_features) of SCORED
R5: list[tuple[str, float, int, list[dict[str, float | str]]]] = [
    (
        "C-C03-20260305",
        0.912345,
        1,
        [
            {"feature": "network_alerts", "value": 1.0, "contribution": 1.5},
            {"feature": "alerts", "value": 2.0, "contribution": 0.4},
        ],
    ),
    ("C-C01-20260302", 0.8, 2, [{"feature": "network_alerts", "value": 1.0, "contribution": 1.5}]),
    ("C-C04-20260305", 0.8, 3, []),
    ("C-C05-20260630", 0.2, 4, []),
    ("C-C01-20260531", 0.1, 5, []),
]


def score_rows(rows: list[Any] | None = None) -> list[dict[str, Any]]:
    return [
        {"case_id": c, "score": s, "queue_rank": r, "top_features": f} for c, s, r, f in rows or R5
    ]


def insert_scores(db: Database, *, score_run_id: int, rows: list[dict[str, Any]]) -> None:
    mod("aml.cases.prio_store").insert_scores(
        db,
        score_run_id=score_run_id,
        run_id=1,
        model_id=1,
        version=f"prio/logreg/{score_run_id}",
        rows=rows,
    )


def scored(db: Database) -> Database:
    """SCORED = API-MINI (already built by the ``api_mini`` fixture) + one scoring run."""
    insert_scores(db, score_run_id=1, rows=score_rows())
    # the spec names version "prio/logreg/1" for score run 1
    return db


def build_minigt(db: Database) -> Database:
    """MINI-GT: MINI-C + ground truth + ``run_cases`` (run 1, 5 cases)."""
    minigt(db)
    return db


def build_minis(db: Database) -> Database:
    """MINI-S: ``load_minis`` + run 1, FALSE_POSITIVE of C-C05-20260630 by analyst01, run 2."""
    settings = api_settings()
    load_minis(db)
    runner = mod("aml.cases.runner")
    runner.run_cases(db, settings)
    dispose(db, settings, C5, "FALSE_POSITIVE", actor="analyst01")
    runner.run_cases(db, settings)
    return db


def rows_of(db: Database) -> dict[str, int]:
    """ROWS(db): the row count of every regular table."""
    names = db.query_df(
        "SELECT table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE' "
        "ORDER BY table_name"
    )
    return {str(n): count(db, str(n)) for n in names.iloc[:, 0]}


def fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    llm: Any = None,
    retriever: Any = None,
    knowledge: Any = None,
) -> tuple[Any, Any, Any]:
    """FAKES: replace the three default factories the API must go through (as the 8c CLI tests)."""
    llm = llm if llm is not None else LLM()
    retriever = retriever if retriever is not None else R4()
    knowledge = knowledge if knowledge is not None else K3()
    monkeypatch.setattr(mod("aml.assistant.answering"), "default_llm", lambda settings: llm)
    monkeypatch.setattr(
        mod("aml.assistant.answering"), "default_retriever", lambda settings: retriever
    )
    monkeypatch.setattr(
        mod("aml.assistant.narrative"), "default_knowledge", lambda settings: knowledge
    )
    return llm, retriever, knowledge


def screening_eval_table() -> pd.DataFrame:
    return pd.read_csv(SCREENING_EVAL_CSV)


def patch_evaluate(monkeypatch: pytest.MonkeyPatch, table: pd.DataFrame | None = None) -> None:
    """Make ``evaluate(db, settings)`` of the screening evaluator return the Phase 3 CSV table.

    The spec says "``evaluate`` is monkeypatched" without naming the module that holds the name,
    so every loaded ``aml.metrics*`` / ``aml.api*`` module that bound the original function is
    patched together with ``aml.screening.evaluate`` itself.
    """
    frame = screening_eval_table() if table is None else table
    mod("aml.metrics")
    mod("aml.api.app")
    target = mod("aml.screening.evaluate")
    original = target.evaluate

    def fake(db: Any, settings: Any) -> pd.DataFrame:
        return frame.copy()

    monkeypatch.setattr(target, "evaluate", fake)
    for name, module in list(sys.modules.items()):
        if (
            name.startswith(("aml.metrics", "aml.api"))
            and getattr(module, "evaluate", None) is original
        ):
            monkeypatch.setattr(module, "evaluate", fake)


def data_of(resp: Any) -> Any:
    """``resp.json()["data"]`` after proving the call succeeded (a missing route is a 404)."""
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def text_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in suffixes)
