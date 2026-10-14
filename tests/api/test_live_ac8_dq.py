"""AC8 of specs/ui-live-pages.md: GET /api/v1/dq/results and /api/v1/dq/trend."""

from __future__ import annotations

import re
from typing import Any

import pytest

from .helpers import api_settings, mod
from .live_helpers import V1, assert_error, audit_total

RESULT_KEYS = [
    "rule_id",
    "table_name",
    "dimension",
    "scope",
    "description",
    "max_fail_rate",
    "total_rows",
    "failed_rows",
    "fail_rate",
    "status",
    "sample_ids",
    "prev_failed_rows",
    "delta_failed_rows",
]
TREND_KEYS = [
    "rule_id",
    "table_name",
    "dimension",
    "run_id",
    "run_ts",
    "failed_rows",
    "fail_rate",
    "status",
    "prev_failed_rows",
    "delta_failed_rows",
]
RULE = "KYC_OCCUPATION_MISSING"
KYC_RUN2 = {
    "rule_id": RULE,
    "table_name": "customers",
    "dimension": "COMPLETENESS",
    "scope": "ROW",
    "description": "occupation is NULL",
    "max_fail_rate": 0.0,
    "total_rows": 6,
    "failed_rows": 0,
    "fail_rate": 0.0,
    "status": "PASS",
    "sample_ids": [],
    "prev_failed_rows": 1,
    "delta_failed_rows": -1,
}


@pytest.fixture
def dq_two_runs(api_mini: Any) -> Any:
    run_dq = mod("aml.dq.runner").run_dq
    run_dq(api_mini, api_settings())
    api_mini.execute("UPDATE customers SET occupation = 'X' WHERE cif = 'C02'")
    run_dq(api_mini, api_settings())
    return api_mini


def test_ac8_results_latest_run(dq_two_runs: Any, client: Any) -> None:
    before = audit_total(dq_two_runs)
    r = client(user="analyst01").get(f"{V1}/dq/results")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "live"
    assert body["feature"] == "dq"
    meta = body["meta"]
    assert sorted(meta) == sorted(
        ["run_id", "as_of", "run_ts", "rules", "passed", "failed", "no_data"]
    )
    assert meta["run_id"] == 2
    assert meta["as_of"] == "2026-06-30"
    assert (meta["rules"], meta["passed"], meta["failed"], meta["no_data"]) == (10, 9, 1, 0)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", meta["run_ts"])
    data = body["data"]
    ids = [d["rule_id"] for d in data]
    assert len(data) == 10
    assert ids == sorted(ids)
    for d in data:
        assert sorted(d) == sorted(RESULT_KEYS)
    by = {d["rule_id"]: d for d in data}
    assert by[RULE] == KYC_RUN2
    stale = by["TXN_FEED_STALE"]
    assert stale["scope"] == "TABLE"
    assert stale["total_rows"] == 1
    assert stale["failed_rows"] == 1
    assert stale["fail_rate"] == 1.0
    assert stale["status"] == "FAIL"
    assert stale["sample_ids"] == ["transactions"]
    assert stale["prev_failed_rows"] == 1
    assert stale["delta_failed_rows"] == 0
    assert audit_total(dq_two_runs) == before


def test_ac8_results_run_1(dq_two_runs: Any, client: Any) -> None:
    body = client(user="analyst01").get(f"{V1}/dq/results?run_id=1").json()
    assert body["meta"]["run_id"] == 1
    assert body["meta"]["passed"] == 8
    assert body["meta"]["failed"] == 2
    kyc = next(d for d in body["data"] if d["rule_id"] == RULE)
    assert kyc["failed_rows"] == 1
    assert kyc["fail_rate"] == 0.166667
    assert kyc["status"] == "FAIL"
    assert kyc["sample_ids"] == ["C02"]
    assert kyc["prev_failed_rows"] is None
    assert kyc["delta_failed_rows"] is None


def test_ac8_results_bad_run_id(dq_two_runs: Any, client: Any) -> None:
    c = client(user="analyst01")
    assert_error(c.get(f"{V1}/dq/results?run_id=9"), 404, "not_found", "unknown dq run 9")
    assert_error(c.get(f"{V1}/dq/results?run_id=abc"), 422, "invalid_request")


def test_ac8_trend_all_rules(dq_two_runs: Any, client: Any) -> None:
    before = audit_total(dq_two_runs)
    r = client(user="analyst01").get(f"{V1}/dq/trend")
    assert r.status_code == 200
    body = r.json()
    assert body["feature"] == "dq"
    assert body["meta"] == {"runs": [1, 2], "rules": 10}
    data = body["data"]
    assert len(data) == 20
    keys = [(d["rule_id"], d["run_id"]) for d in data]
    assert keys == sorted(keys)
    for d in data:
        assert sorted(d) == sorted(TREND_KEYS)
    assert audit_total(dq_two_runs) == before


def test_ac8_trend_one_rule(dq_two_runs: Any, client: Any) -> None:
    c = client(user="analyst01")
    data = c.get(f"{V1}/dq/trend?rule_id={RULE}").json()["data"]
    rows = [
        (
            d["run_id"],
            d["failed_rows"],
            d["fail_rate"],
            d["status"],
            d["prev_failed_rows"],
            d["delta_failed_rows"],
        )
        for d in data
    ]
    assert rows == [(1, 1, 0.166667, "FAIL", None, None), (2, 0, 0.0, "PASS", 1, -1)]
    other = c.get(f"{V1}/dq/trend?rule_id=NOPE")
    assert other.status_code == 200
    assert other.json()["data"] == []


def test_ac8_trend_runs_limit(dq_two_runs: Any, client: Any) -> None:
    c = client(user="analyst01")
    body = c.get(f"{V1}/dq/trend?runs=1").json()
    assert len(body["data"]) == 10
    assert all(d["run_id"] == 2 for d in body["data"])
    assert body["meta"]["runs"] == [2]
    kyc = next(d for d in body["data"] if d["rule_id"] == RULE)
    assert kyc["prev_failed_rows"] == 1
    assert_error(c.get(f"{V1}/dq/trend?runs=0"), 422, "invalid_request")


def test_ac8_supervisor_gets_same_data_without_pii_meta(dq_two_runs: Any, client: Any) -> None:
    before = audit_total(dq_two_runs)
    a, s = client(user="analyst01"), client(user="supervisor01")
    for path in (f"{V1}/dq/results", f"{V1}/dq/trend"):
        ra, rs = a.get(path), s.get(path)
        assert ra.json()["data"] == rs.json()["data"]
        assert "pii" not in ra.json()["meta"]
        assert "pii" not in rs.json()["meta"]
    assert audit_total(dq_two_runs) == before


def test_ac8_before_any_dq_run(schema: Any, client: Any) -> None:
    c = client(user="analyst01")
    results = c.get(f"{V1}/dq/results")
    assert results.status_code == 200
    assert results.json()["data"] == []
    assert results.json()["meta"] == {
        "run_id": None,
        "as_of": None,
        "run_ts": None,
        "rules": 0,
        "passed": 0,
        "failed": 0,
        "no_data": 0,
    }
    trend = c.get(f"{V1}/dq/trend")
    assert trend.status_code == 200
    assert trend.json()["data"] == []
    assert trend.json()["meta"] == {"runs": [], "rules": 0}
