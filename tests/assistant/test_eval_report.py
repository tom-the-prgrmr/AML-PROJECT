"""AC7 for specs/assistant-eval.md: result file, Markdown report, item table, `--report-only`."""

from __future__ import annotations

import csv
import io
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import get_settings
from aml.common.db import DuckDb

from .ev_helpers import cli, count, gold, load_mini_g, mod, ratio, report_mod, sample_result

VECTOR_NOTE = (
    "plain vector mode never reads transaction memos, so its injection resistance is n/a by design"
)
TABLE_LINES = [
    "| metric | vector | graphrag |",
    "| answer correctness | 6/11 (54.5%) | 10/11 (90.9%) |",
    "| citation precision | 10/12 (83.3%) | 21/22 (95.5%) |",
    "| hallucination rate | 4/11 (36.4%) | 0/11 (0.0%) |",
    "| refusal correctness | 11/15 (73.3%) | 15/15 (100.0%) |",
    "| injection resistance | 0/1 (0.0%) | 2/2 (100.0%) |",
    "| injection exposed | 1/2 | 2/2 |",
    "| unanswerable refused | 2/4 | 4/4 |",
    "| answerable refused | 2/11 | 0/11 |",
    "| uncited answers | 1 | 0 |",
    "| errors | 0 | 0 |",
    "| type | items | vector | graphrag |",
    "| fact | 4 | 2/4 | 4/4 |",
    "| multi_hop | 2 | 0/2 | 2/2 |",
    "| typology | 3 | 2/3 | 2/3 |",
    "| unanswerable | 4 | 2/4 | 4/4 |",
    "| injection | 2 | 2/2 | 2/2 |",
]


@pytest.fixture
def golden(duck: DuckDb, tmp_path: Path) -> Any:
    return gold(load_mini_g(duck), tmp_path)


@pytest.fixture
def result(golden: Any) -> Any:
    return sample_result(golden)


def test_ac7_report_tables(result: Any) -> None:
    lines = report_mod().render_report(result).splitlines()
    for expected in TABLE_LINES:
        assert lines.count(expected) == 1, expected


def test_ac7_report_provenance_and_no_verdict(result: Any, golden: Any) -> None:
    text = report_mod().render_report(result)
    for needle in ("aml rag eval", "m1", "e1", "p1", "seed: 42", golden.meta["fingerprint"]):
        assert needle in text, needle
    assert "- seed: 42" in text.splitlines()
    assert VECTOR_NOTE in text
    lowered = text.lower()
    for banned in ("better", "outperform", "wins", "partial run", "side effects"):
        assert banned not in lowered, banned


def test_ac7_result_round_trip(result: Any, tmp_path: Path) -> None:
    out = tmp_path / "out"
    path = report_mod().write_result(result, out)
    assert path == out / "eval_result.json"
    back = report_mod().read_result(out)
    assert back.meta == result.meta
    assert back.scores == result.scores
    assert back.metrics == result.metrics
    assert report_mod().render_report(back) == report_mod().render_report(result)


def test_ac7_write_report_files(result: Any, tmp_path: Path) -> None:
    out = tmp_path / "out"
    report_mod().write_result(result, out)
    report, items = report_mod().write_report(out)
    assert (report, items) == (out / "eval_report.md", out / "eval_items.csv")
    assert report.read_bytes() == report_mod().render_report(result).encode("utf-8")
    rows = list(csv.DictReader(io.StringIO(items.read_text(encoding="utf-8"))))
    assert len(rows) == 30
    assert len(items.read_text(encoding="utf-8").splitlines()) == 31
    for column in ("template", "language", "seconds"):
        assert column in rows[0]
    row = next(r for r in rows if (r["item_id"], r["mode"]) == ("G-M01", "vector"))
    assert row["correct"] == "False"
    assert row["cited"] == "2"
    assert row["cited_supported"] == "1"
    assert row["unknown_ids"] == "T99"
    assert row["template"] == "hop_round_trip"
    first = (report.read_bytes(), items.read_bytes())
    report_mod().write_report(out)
    assert (report.read_bytes(), items.read_bytes()) == first


def test_ac7_partial_and_side_effect_lines(golden: Any) -> None:
    render = report_mod().render_report
    partial = render(sample_result(golden, partial=True, items_answered=2)).splitlines()
    assert partial.count("PARTIAL RUN: 2 of 15 questions") == 1
    changed = render(sample_result(golden, side_effects={"case_dispositions": 1})).splitlines()
    assert changed.count("SIDE EFFECTS: case_dispositions +1") == 1


def test_ac7_ratio_without_denominator_prints_na(result: Any) -> None:
    vector = replace(result.metrics["vector"], injection_resistance=ratio(0, 0))
    changed = replace(result, metrics={**result.metrics, "vector": vector})
    lines = report_mod().render_report(changed).splitlines()
    assert "| injection resistance | n/a | 2/2 (100.0%) |" in lines


# ---------------------------------------------------------------- CLI --report-only
@pytest.fixture
def report_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A DuckDB with the schema only and an empty results directory."""
    db_path = tmp_path / "rep.duckdb"
    with DuckDb(db_path) as db:
        mod("aml.dba.schema").apply_schema(db)
    out = tmp_path / "results"
    out.mkdir()
    for name, value in {
        "DB_BACKEND": "duckdb",
        "AML__DB__DUCKDB_PATH": str(db_path),
        "AML__RAG_EVAL__RESULTS_DIR": str(out),
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    return tmp_path


def test_ac7_report_only_without_a_result(report_env: Path) -> None:
    done = cli("rag", "eval", "--report-only")
    assert done.exit_code == 1, done.output
    assert "no evaluation result" in done.stderr
    assert "Traceback" not in done.stderr


def test_ac7_report_only_rebuilds_from_the_file(report_env: Path, result: Any) -> None:
    out = report_env / "results"
    report_mod().write_result(result, out)
    done = cli("rag", "eval", "--report-only")
    assert done.exit_code == 0, done.output
    assert len([ln for ln in done.stdout.splitlines() if ln.startswith("wrote")]) == 2
    assert (out / "eval_report.md").read_text(encoding="utf-8") == report_mod().render_report(
        result
    )
    with DuckDb(report_env / "rep.duckdb") as db:
        assert count(db, "audit_log") == 0
