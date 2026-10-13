"""AC6 of specs/ui-foundation.md: POST /api/v1/cases/{id}/disposition (decision convention)."""

from __future__ import annotations

from typing import Any

import pytest

from .helpers import CASE_C05, audit_rows, count, error_of, query

URL = f"/api/v1/cases/{CASE_C05}/disposition"
GOOD = {"disposition": "FALSE_POSITIVE", "reason": "name only match"}


def test_ac6_post_records_disposition(api_mini: Any, client: Any) -> None:
    r = client(user="analyst01").post(URL, json=GOOD)
    assert r.status_code == 201
    assert r.json() == {
        "source": "live",
        "feature": "cases",
        "data": {
            "disposition_id": 1,
            "case_id": CASE_C05,
            "disposition": "FALSE_POSITIVE",
            "actor": "analyst01",
            "decided_on": "2026-06-30",
        },
        "meta": {},
    }
    rows = query(api_mini, "SELECT * FROM case_dispositions")
    assert len(rows) == 1
    row = rows.iloc[0]
    assert (row["case_id"], int(row["run_id"]), row["actor"], row["origin"]) == (
        CASE_C05,
        1,
        "analyst01",
        "HUMAN",
    )
    # run_cases already wrote one CASE_OPENED row per case; the request adds exactly one more
    audit = audit_rows(api_mini, "entity_type = 'case' AND decision <> 'CASE_OPENED'")
    assert len(audit) == 1
    a = audit[0]
    assert a["module"] == "cases"
    assert a["entity_id"] == CASE_C05
    assert a["decision"] == "FALSE_POSITIVE"
    assert a["actor"] == "analyst01"
    assert a["reason"] == "name only match"
    assert a["details"]["disposition_id"] == 1


def test_ac6_queue_shows_disposition_but_keeps_status(api_mini: Any, client: Any) -> None:
    c = client(user="analyst01")
    assert c.post(URL, json=GOOD).status_code == 201
    case = next(x for x in c.get("/api/v1/cases").json()["data"] if x["case_id"] == CASE_C05)
    assert case["status"] == "OPEN"
    assert case["disposition"] == {
        "disposition": "FALSE_POSITIVE",
        "actor": "analyst01",
        "decided_on": "2026-06-30",
    }


def test_ac6_second_decision_by_supervisor(api_mini: Any, client: Any) -> None:
    assert client(user="analyst01").post(URL, json=GOOD).status_code == 201
    r = client(user="supervisor01").post(
        URL, json={"disposition": "SUSPICIOUS", "reason": "second review"}
    )
    assert r.status_code == 201
    assert r.json()["data"]["disposition_id"] == 2
    assert r.json()["data"]["actor"] == "supervisor01"
    audit = audit_rows(api_mini, "entity_type = 'case' AND actor = 'supervisor01'")
    assert len(audit) == 1


@pytest.mark.parametrize(
    ("url", "body", "status", "code"),
    [
        (URL, {**GOOD, "actor": "boss"}, 422, "invalid_request"),
        (URL, {**GOOD, "reason": ""}, 422, "invalid_request"),
        (URL, {**GOOD, "reason": "   "}, 422, "invalid_request"),
        (URL, {"disposition": "FALSE_POSITIVE"}, 422, "invalid_request"),
        (URL, {**GOOD, "disposition": "CLOSED"}, 422, "invalid_request"),
        ("/api/v1/cases/C-NOPE-20260101/disposition", GOOD, 404, "not_found"),
    ],
)
def test_ac6_rejected_requests_write_nothing(
    api_mini: Any, client: Any, url: str, body: dict[str, Any], status: int, code: str
) -> None:
    disp, audit = count(api_mini, "case_dispositions"), count(api_mini, "audit_log")
    r = client(user="analyst01").post(url, json=body)
    assert r.status_code == status
    assert error_of(r)["code"] == code
    if status == 404:
        assert "unknown case_id" in error_of(r)["message"]
    assert count(api_mini, "case_dispositions") == disp
    assert count(api_mini, "audit_log") == audit


def test_ac6_delete_is_405_and_writes_nothing(api_mini: Any, client: Any) -> None:
    disp, audit = count(api_mini, "case_dispositions"), count(api_mini, "audit_log")
    r = client(user="analyst01").delete(URL)
    assert r.status_code == 405
    assert count(api_mini, "case_dispositions") == disp
    assert count(api_mini, "audit_log") == audit


def test_ac6_missing_user_is_401_and_writes_nothing(api_mini: Any, client: Any) -> None:
    disp, audit = count(api_mini, "case_dispositions"), count(api_mini, "audit_log")
    r = client(AML__UI__DEFAULT_USER="").post(URL, json=GOOD)
    assert r.status_code == 401
    assert error_of(r)["code"] == "missing_user"
    assert count(api_mini, "case_dispositions") == disp
    assert count(api_mini, "audit_log") == audit
