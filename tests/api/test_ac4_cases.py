"""AC4 of specs/ui-foundation.md: GET /api/v1/cases."""

from __future__ import annotations

from typing import Any

import pytest

from .helpers import CASE_C01_A, CASE_KEYS, MINI_ORDER, error_of

CASES = "/api/v1/cases"
META = {"run_id": 1, "as_of": "2026-06-30", "total": 5, "limit": 50, "offset": 0}
C01_A = {
    "case_id": CASE_C01_A,
    "golden_customer_id": "G-C01",
    "status": "OPEN",
    "alerts": 3,
    "rule_alerts": 2,
    "network_alerts": 1,
    "screening_alerts": 0,
    "sources": ["NETWORK", "RULE"],
    "window_start": "2026-03-02T09:00:00",
    "first_alert_ts": "2026-03-02T09:00:00",
    "last_alert_ts": "2026-04-20T12:00:00",
    "reason": "3 alert(s) (2 RULE, 1 NETWORK, 0 SCREENING) on G-C01 between "
    "2026-03-02 09:00:00 and 2026-04-20 12:00:00; window of 90 days from the first alert",
    "disposition": None,
}


def test_ac4_list_order_meta_and_keys(api_mini: Any, client: Any) -> None:
    r = client().get(CASES)
    body = r.json()
    assert r.status_code == 200
    assert body["source"] == "live"
    assert body["feature"] == "cases"
    assert body["meta"] == META
    assert [c["case_id"] for c in body["data"]] == MINI_ORDER
    for case in body["data"]:
        assert set(case) == CASE_KEYS
        assert not {"score", "queue_rank", "priority"} & set(case)


def test_ac4_case_values(api_mini: Any, client: Any) -> None:
    data = client().get(CASES).json()["data"]
    by_id = {c["case_id"]: c for c in data}
    assert by_id[CASE_C01_A] == C01_A
    assert data[0]["sources"] == ["RULE", "SCREENING"]
    assert data[0]["last_alert_ts"] == "2026-06-30T00:00:00"


def test_ac4_no_pii_in_queue(api_mini: Any, client: Any) -> None:
    assert "Nguyen" not in client().get(CASES).text


def test_ac4_filter_and_paging(api_mini: Any, client: Any) -> None:
    body = client().get(CASES, params={"status": "OPEN", "limit": 2, "offset": 4}).json()
    assert [c["case_id"] for c in body["data"]] == ["C-C04-20260305"]
    assert body["meta"] == {"run_id": 1, "as_of": "2026-06-30", "total": 5, "limit": 2, "offset": 4}


def test_ac4_closed_filter_is_empty(api_mini: Any, client: Any) -> None:
    body = client().get(CASES, params={"status": "CLOSED"}).json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


@pytest.mark.parametrize(
    "params", [{"status": "BOGUS"}, {"limit": 0}, {"limit": 201}, {"offset": -1}]
)
def test_ac4_invalid_params_are_422(api_mini: Any, client: Any, params: dict[str, Any]) -> None:
    r = client().get(CASES, params=params)
    assert r.status_code == 422
    assert error_of(r)["code"] == "invalid_request"


def test_ac4_page_size_comes_from_config(api_mini: Any, client: Any) -> None:
    body = client(AML__UI__PAGE_SIZE="2").get(CASES).json()
    assert len(body["data"]) == 2
    assert body["meta"]["limit"] == 2


def test_ac4_no_case_run_yet(schema: Any, client: Any) -> None:
    r = client().get(CASES)
    assert r.status_code == 200
    assert r.json()["data"] == []
    assert r.json()["meta"] == {"run_id": None, "as_of": None, "total": 0, "limit": 50, "offset": 0}
