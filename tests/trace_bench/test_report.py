"""AC4 for specs/trace-benchmark.md: Markdown report, SVG chart, `--report-only` (no services)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aml.common.db import DuckDb

from .helpers import cli, make_sample, mod, set_env

LINES = [
    "| small | oracle | A1 | 720 | 6 | cte_raw | ok | 22394 | 600.0 | 780.0 | 30 |  |",
    "| small | oracle | A1 | 720 | 6 | cte_edge | ok | 27 | 4.0 | 4.0 | 38 | "
    "approximate (daily edges, top-K): paths not comparable |",
    "| small | oracle | A1 | 720 | 6 | pgq | error |  |  |  |  | "
    "TraceError: more than 100000 paths |",
    "| small | oracle | A1 | 720 | 6 | neo4j | skipped |  |  |  |  | neo4j not available |",
]


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    out = tmp_path / "results"
    out.mkdir()
    mod("aml.graph.bench.report").write_result(make_sample(), out)
    return out


def test_ac4_report_rows_and_notes() -> None:
    report = mod("aml.graph.bench.report")
    text = report.render_report([make_sample()])
    rows = text.splitlines()
    for line in LINES:
        assert line in rows, line
    assert "aml bench" in text
    assert "linear interpolation" in text
    assert "SQL is enough" not in text


def test_ac4_report_from_files_equals_report_from_memory(sample_dir: Path) -> None:
    report = mod("aml.graph.bench.report")
    assert report.render_report([make_sample()]) == report.render_report(
        report.read_results(sample_dir)
    )


def test_ac4_write_report_files(sample_dir: Path) -> None:
    report = mod("aml.graph.bench.report")
    md, svg = report.write_report(sample_dir)
    assert (md, svg) == (sample_dir / "bench_report.md", sample_dir / "bench_chart.svg")
    assert md.is_file() and svg.is_file()
    assert md.read_text(encoding="utf-8") == report.render_report([make_sample()])
    chart = svg.read_text(encoding="utf-8")
    assert "<svg" in chart
    assert "cte_raw" in chart
    assert "cte_edge" in chart
    assert "neo4j" not in chart  # the only neo4j cell is skipped, so it has no line


def test_ac4_write_report_is_byte_identical(sample_dir: Path) -> None:
    report = mod("aml.graph.bench.report")
    md, svg = report.write_report(sample_dir)
    first = (md.read_bytes(), svg.read_bytes())
    report.write_report(sample_dir)
    assert (md.read_bytes(), svg.read_bytes()) == first


def test_ac4_cli_report_only_without_results_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    set_env(monkeypatch, {"DB_BACKEND": "duckdb", "AML__BENCH__RESULTS_DIR": str(empty)})
    result = cli("bench", "--report-only")
    assert result.exit_code == 1, result.output
    assert "no benchmark results" in result.stderr


def test_ac4_cli_report_only_writes_two_files_and_no_audit(
    sample_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "audit.duckdb"
    with DuckDb(db_path) as db:
        mod("aml.dba.schema").apply_schema(db)
    set_env(
        monkeypatch,
        {
            "DB_BACKEND": "duckdb",
            "AML__DB__DUCKDB_PATH": str(db_path),
            "AML__BENCH__RESULTS_DIR": str(sample_dir),
        },
    )
    result = cli("bench", "--report-only")
    assert result.exit_code == 0, result.output
    assert len([ln for ln in result.stdout.splitlines() if ln.startswith("wrote")]) == 2
    assert (sample_dir / "bench_report.md").is_file()
    assert (sample_dir / "bench_chart.svg").is_file()
    with DuckDb(db_path) as db:
        assert int(db.query_df("SELECT COUNT(*) FROM audit_log").iloc[0, 0]) == 0
