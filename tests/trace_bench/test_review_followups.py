"""Review follow-ups for specs/trace-benchmark.md (no service needed): the report warns when the
exact methods disagree on the paths, and a profile label that cannot be a file name is refused
before anything is timed."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from aml.common.db import DuckDb
from aml.graph.bench.model import BenchError, BenchResult
from aml.graph.bench.report import path_mismatches, render_report
from aml.graph.bench.runner import run_bench

from .helpers import bench_settings, make_sample


def _with_wrong_neo4j_count(sample: BenchResult) -> BenchResult:
    """The sample with a made-up `neo4j` cell that is ok but found one path too few."""
    cells = list(sample.cells)
    base = next(c for c in cells if c.method == "cte_raw" and c.status == "ok")
    cells.append(replace(base, method="neo4j", n_paths=(base.n_paths or 0) - 1))
    return BenchResult(sample.meta, cells)


def test_agreeing_exact_methods_give_no_warning() -> None:
    sample = make_sample()
    assert path_mismatches(sample) == []
    assert "Warning" not in render_report([sample])


def test_disagreeing_exact_methods_are_called_out() -> None:
    sample = _with_wrong_neo4j_count(make_sample())
    mismatches = path_mismatches(sample)
    assert len(mismatches) == 1
    assert "cte_raw" in mismatches[0] and "neo4j" in mismatches[0]
    assert "**Warning: the exact methods disagree on the paths**" in render_report([sample])


def test_approximate_method_is_not_compared() -> None:
    sample = make_sample()
    cells = [replace(c, n_paths=(c.n_paths or 0) + 5) if not c.exact else c for c in sample.cells]
    assert path_mismatches(BenchResult(sample.meta, cells)) == []


@pytest.mark.parametrize("label", ["a/b", "up..one/x", "has space"])
def test_bad_profile_label_is_refused_before_timing(
    duck: DuckDb, tmp_path: Path, label: str
) -> None:
    with pytest.raises(BenchError, match="profile label"):
        run_bench(duck, bench_settings(tmp_path), profile=label)
