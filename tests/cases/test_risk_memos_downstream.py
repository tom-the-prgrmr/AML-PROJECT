"""AC7 for specs/datagen-memos.md: Phase 3-7 results do not depend on the ``memo`` column.

B = the TINY stages already built for the cases tests (``tiny_stages["full"]``, risk memos on).
A = the same chain on a TINY run with both risk-memo rates at 0 (one extra chain, built once).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from aml.common.db import DuckDb
from tests.datagen.risk_memo_helpers import OFF, run_tiny

from .helpers import duck_settings, load_tiny_duck, mod, query, run_cases

QUERIES = {
    "dq": (
        "SELECT rule_id, status, failed_rows, total_rows FROM dq_results "
        "WHERE run_id = (SELECT MAX(run_id) FROM dq_results) ORDER BY rule_id"
    ),
    "golden": "SELECT cif, golden_customer_id FROM customer_golden ORDER BY cif",
    "screening": (
        "SELECT cif, entry_id, decision, final_score FROM screening_current ORDER BY cif, entry_id"
    ),
    "alerts": (
        "SELECT rule_id, alert_key, amount_vnd FROM alerts_current ORDER BY rule_id, alert_key"
    ),
    "cases": (
        "SELECT case_id, golden_customer_id, alerts, sources, status FROM cases_current "
        "ORDER BY case_id"
    ),
    "enrichment": (
        "SELECT case_id, section, content FROM case_enrichment_current ORDER BY case_id, section"
    ),
}


@pytest.fixture(scope="module")
def run_a(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, object]:
    root = tmp_path_factory.mktemp("rm_a")
    pq = run_tiny(root / "pq", **OFF)
    settings = duck_settings()
    db = load_tiny_duck(pq, root / "a.duckdb")
    try:
        mod("aml.entity_resolution.runner").run_er(db, settings)
        mod("aml.screening.runner").run_screening(db, settings)
        mod("aml.monitoring.runner").run_monitoring(db, settings)
        mod("aml.graph.network.runner").run_network(db, settings)
        mod("aml.dq.runner").run_dq(db, settings)
        run = run_cases(db, settings)
    finally:
        db.close()
    return root / "a.duckdb", run


@pytest.fixture(scope="module")
def run_b(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, object]:
    root = tmp_path_factory.mktemp("rm_b")
    target = root / "b.duckdb"
    shutil.copy(tiny_stages["full"], target)
    db = DuckDb(target)
    try:
        run = run_cases(db, duck_settings())
    finally:
        db.close()
    return target, run


def _frames(path: Path) -> dict[str, pd.DataFrame]:
    db = DuckDb(path)
    try:
        return {name: query(db, sql) for name, sql in QUERIES.items()}
    finally:
        db.close()


def test_ac7_downstream_results_do_not_depend_on_memo(
    run_a: tuple[Path, object], run_b: tuple[Path, object]
) -> None:
    (path_a, summary_a), (path_b, summary_b) = run_a, run_b
    for summary in (summary_a, summary_b):
        assert summary.cases == 52  # type: ignore[attr-defined]
        assert summary.items == 74  # type: ignore[attr-defined]
    frames_a, frames_b = _frames(path_a), _frames(path_b)
    for name in QUERIES:
        assert len(frames_a[name]) > 0, name
        pd.testing.assert_frame_equal(frames_a[name], frames_b[name], obj=name)
