"""AC1 for specs/trace-benchmark.md: bench config, statistics, docs (no services)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aml.common.config import load_settings

from .helpers import REPO, mod


def test_ac1_bench_config_defaults() -> None:
    bench = load_settings(environ={}).bench
    assert bench.hops == [2, 4, 6]
    assert bench.hours == [72, 720]
    assert bench.runs == 10
    assert bench.warmup_runs == 1
    assert bench.accounts == []
    assert bench.top_accounts == 1
    assert bench.results_dir == "results/phase6"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"AML__BENCH__RUNS": "4"}, "runs must be >= 5"),
        ({"AML__BENCH__HOPS": "[2, 7]"}, "hops must be between 1 and 6"),
        ({"AML__BENCH__HOURS": "[721]"}, "hours must be between 1 and 720"),
        ({"AML__BENCH__HOPS": "[]"}, "hops must not be empty"),
        ({"AML__BENCH__TOP_ACCOUNTS": "0"}, "top_accounts must be between 1 and 10"),
    ],
)
def test_ac1_bench_config_validation(env: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        load_settings(environ=env)


def test_ac1_median() -> None:
    stats = mod("aml.graph.bench.stats")
    assert stats.median([10, 20, 30, 40, 100]) == 30
    assert stats.median([4, 1, 3, 2]) == 2.5
    assert stats.median([10, 20]) == 15


def test_ac1_percentile() -> None:
    stats = mod("aml.graph.bench.stats")
    assert stats.percentile([10, 20, 30, 40, 100], 95) == pytest.approx(88.0)
    assert stats.percentile([100, 10, 40, 20, 30], 95) == pytest.approx(88.0)
    assert stats.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == pytest.approx(9.55)
    assert stats.percentile([5.0], 95) == 5.0
    assert stats.percentile([10, 20], 50) == stats.median([10, 20]) == 15


def test_ac1_stats_errors() -> None:
    stats = mod("aml.graph.bench.stats")
    with pytest.raises(ValueError, match="empty"):
        stats.median([])
    with pytest.raises(ValueError, match="empty"):
        stats.percentile([], 95)
    with pytest.raises(ValueError, match="between 0 and 100"):
        stats.percentile([1], 101)


def test_ac1_docs_exist_with_required_words() -> None:
    path = REPO / "docs" / "trace-benchmark.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    for word in ("aml bench", "aml graph sync --full", "warm", "p95", "cte_edge"):
        assert word in text, word
