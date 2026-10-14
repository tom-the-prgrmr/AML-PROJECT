"""AC9 of specs/ui-live-pages.md: GET /api/v1/benchmark (reads the bench result files)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from aml.graph.bench.model import BenchCell, BenchResult
from aml.graph.bench.report import NOTES, write_result

from .helpers import API_SRC
from .live_helpers import V1, audit_total

URL = f"{V1}/benchmark"
EMPTY = {
    "source": "live",
    "feature": "benchmark",
    "data": {"runs": [], "notes": []},
    "meta": {"files": 0},
}
META_A = {
    "schema": "bench/v1",
    "profile": "small",
    "backend": "duckdb",
    "command": "aml bench --profile small",
    "started_at": "2026-10-13T04:48:39+00:00",
    "total_seconds": 1.5,
    "git_commit": "abc1234",
}
CELL_OK = BenchCell(
    "cte_raw",
    "A1",
    72,
    2,
    "ok",
    None,
    True,
    (0.010, 0.020, 0.030),
    20.0,
    29.0,
    10.0,
    30.0,
    4,
    3,
    1,
    38,
)
CELL_SKIP = BenchCell(
    "neo4j",
    "A1",
    72,
    2,
    "skipped",
    "neo4j not available",
    True,
    (),
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
)
CELL_PGQ = replace(CELL_OK, method="pgq", n_paths=5)
OK_JSON = {
    "method": "cte_raw",
    "account": "A1",
    "hours": 72,
    "hops": 2,
    "status": "ok",
    "reason": None,
    "exact": True,
    "runs": 3,
    "median_ms": 20.0,
    "p95_ms": 29.0,
    "min_ms": 10.0,
    "max_ms": 30.0,
    "n_paths": 4,
    "n_accounts": 3,
    "n_cycles": 1,
    "query_lines": 38,
}
SKIP_JSON = {
    "method": "neo4j",
    "account": "A1",
    "hours": 72,
    "hops": 2,
    "status": "skipped",
    "reason": "neo4j not available",
    "exact": True,
    "runs": 0,
    "median_ms": None,
    "p95_ms": None,
    "min_ms": None,
    "max_ms": None,
    "n_paths": None,
    "n_accounts": None,
    "n_cycles": None,
    "query_lines": None,
}


def _res(tmp_path: Path) -> Path:
    res = tmp_path / "res"
    res.mkdir()
    return res


def _client(client: Any, res: Path) -> Any:
    return client(user="analyst01", AML__BENCH__RESULTS_DIR=res.as_posix())


def test_ac9_empty_directory(schema: Any, client: Any, tmp_path: Path) -> None:
    before = audit_total(schema)
    r = _client(client, _res(tmp_path)).get(URL)
    assert r.status_code == 200
    assert r.json() == EMPTY
    assert audit_total(schema) == before


def test_ac9_missing_directory(schema: Any, client: Any, tmp_path: Path) -> None:
    r = _client(client, tmp_path / "does-not-exist").get(URL)
    assert r.status_code == 200
    assert r.json() == EMPTY


def test_ac9_one_result_file(schema: Any, client: Any, tmp_path: Path) -> None:
    res = _res(tmp_path)
    write_result(BenchResult(META_A, [CELL_OK, CELL_SKIP]), res)
    r = _client(client, res).get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["meta"] == {"files": 1}
    assert body["data"]["notes"] == list(NOTES)
    runs = body["data"]["runs"]
    assert len(runs) == 1
    run = runs[0]
    assert sorted(run) == ["cells", "file", "meta", "mismatches"]
    assert run["file"] == "bench_small_duckdb.json"
    assert run["meta"] == META_A
    assert run["mismatches"] == []
    assert run["cells"][0] == OK_JSON
    assert run["cells"][1] == SKIP_JSON
    assert all("seconds" not in c for c in run["cells"])


def test_ac9_two_files_mismatch_and_ignored_extras(
    schema: Any, client: Any, tmp_path: Path
) -> None:
    res = _res(tmp_path)
    write_result(BenchResult(META_A, [CELL_OK, CELL_SKIP]), res)
    c = _client(client, res)
    one = c.get(URL).json()
    write_result(
        BenchResult({**META_A, "profile": "dense", "backend": "oracle"}, [CELL_OK, CELL_PGQ]), res
    )
    (res / "notes.txt").write_text("not a result", encoding="utf-8")
    (res / "other.json").write_text("{}", encoding="utf-8")
    body = c.get(URL).json()
    assert body["meta"] == {"files": 2}
    runs = body["data"]["runs"]
    assert [r["file"] for r in runs] == ["bench_dense_oracle.json", "bench_small_duckdb.json"]
    assert runs[0]["mismatches"] == ["A1, T 72 h, 2 hops: cte_raw 4, pgq 5"]
    assert runs[1] == one["data"]["runs"][0]


def test_ac9_corrupt_file_is_internal_error(schema: Any, client: Any, tmp_path: Path) -> None:
    res = _res(tmp_path)
    write_result(BenchResult(META_A, [CELL_OK]), res)
    (res / "bench_bad_x.json").write_text("{", encoding="utf-8")
    before = audit_total(schema)
    r = _client(client, res).get(URL)
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal_error", "message": "internal error"}}
    assert audit_total(schema) == before


def test_ac9_no_bench_fixture_in_api(schema: Any) -> None:
    fixtures = API_SRC / "fixtures"
    assert fixtures.is_dir()
    assert [p.name for p in fixtures.rglob("*") if "bench" in p.name.lower()] == []
    # and the endpoint exists at all (a file-name check alone passes on an empty tree)
    assert (API_SRC / "reads" / "benchmark.py").is_file()
