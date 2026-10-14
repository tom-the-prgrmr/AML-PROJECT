"""AC6 of specs/ui-live-pages.md: GET /api/v1/screening/hits."""

from __future__ import annotations

from typing import Any

import pytest

from .helpers import audit_rows
from .live_helpers import V1, assert_error, audit_total

URL = f"{V1}/screening/hits"
HIT_KEYS = [
    "cif",
    "entry_id",
    "list_type",
    "matched_name",
    "matched_name_type",
    "token_set",
    "jaro_winkler",
    "fuzzy_score",
    "coverage",
    "name_score",
    "final_score",
    "dob_gap_years",
    "decision",
    "reason",
    "run_id",
    "customer",
    "review",
    "case_id",
]
COUNTS = {"ALERT": 1, "REVIEW": 1, "AUTO_CLEARED": 1}
META = {
    "pii": "masked",
    "run_id": 1,
    "as_of": "2026-06-30",
    "total": 3,
    "limit": 50,
    "offset": 0,
    "counts": COUNTS,
    "thresholds": {"alert": 90, "review": 75},
}
FIRST = {
    "cif": "C02",
    "entry_id": "WL1",
    "list_type": "SANCTIONS",
    "matched_name": "LISTED NAME",
    "matched_name_type": "PRIMARY",
    "token_set": 1.0,
    "jaro_winkler": 1.0,
    "fuzzy_score": 1.0,
    "coverage": 1.0,
    "name_score": 1.0,
    "final_score": 100.0,
    "dob_gap_years": None,
    "decision": "ALERT",
    "reason": "test reason",
    "run_id": 1,
    "customer": {
        "cif": "C02",
        "full_name": "Nguyen T. C.",
        "birth_year": 1990,
        "nationality": "VN",
        "gender": "F",
        "id_type": "PASSPORT",
        "id_number": "****4562",
    },
    "review": None,
    "case_id": "C-C01-20260531",
}


def test_ac6_analyst_listing(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    r = client(user="analyst01").get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["feature"] == "screening"
    assert body["meta"] == META
    data = body["data"]
    assert [(h["cif"], h["entry_id"], h["decision"]) for h in data] == [
        ("C02", "WL1", "ALERT"),
        ("C05", "WL2", "REVIEW"),
        ("C06", "WL3", "AUTO_CLEARED"),
    ]
    for h in data:
        assert sorted(h) == sorted(HIT_KEYS)
    assert data[0] == FIRST
    assert data[1]["final_score"] == 80.0
    assert data[1]["case_id"] == "C-C05-20260630"
    assert data[2]["final_score"] == 60.0
    assert data[2]["case_id"] is None
    assert "Nguyen Thi" not in r.text
    assert "B123456" not in r.text
    assert audit_total(api_mini) == before


def test_ac6_filter_and_paging(api_mini: Any, client: Any) -> None:
    c = client(user="analyst01")
    body = c.get(URL + "?decision=AUTO_CLEARED").json()
    assert [h["cif"] for h in body["data"]] == ["C06"]
    assert body["meta"]["total"] == 1
    assert body["meta"]["counts"] == COUNTS
    body = c.get(URL + "?limit=1&offset=1").json()
    assert [h["cif"] for h in body["data"]] == ["C05"]
    assert body["meta"]["total"] == 3


@pytest.mark.parametrize("suffix", ["?decision=BOGUS", "?limit=0"])
def test_ac6_bad_params_are_422(api_mini: Any, client: Any, suffix: str) -> None:
    assert_error(client(user="analyst01").get(URL + suffix), 422, "invalid_request")


def test_ac6_analyst_cannot_unmask_by_query(api_mini: Any, client: Any) -> None:
    body = client(user="analyst01").get(URL + "?masked=false").json()
    assert body["meta"]["pii"] == "masked"


def test_ac6_supervisor_sees_full_customer_and_audit_row(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    r = client(user="supervisor01").get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["pii"] == "full"
    assert body["data"][0]["customer"] == {
        "cif": "C02",
        "full_name": "Nguyen Thi C02",
        "birth_year": 1990,
        "nationality": "VN",
        "gender": "F",
        "id_type": "PASSPORT",
        "id_number": "B1234562",
    }
    assert audit_total(api_mini) == before + 1
    rows = audit_rows(api_mini, "decision = 'PII_VIEWED'")
    assert len(rows) == 1
    row = rows[0]
    assert row["module"] == "ui"
    assert row["entity_type"] == "screening"
    assert row["entity_id"] == "hits"
    assert row["actor"] == "supervisor01"
    assert row["reason"] == "unmasked screening hits shown to supervisor01 (role supervisor)"
    assert row["details"]["cifs"] == ["C02", "C05", "C06"]


def test_ac6_customer_gone_gives_null(api_mini: Any, client: Any) -> None:
    api_mini.execute("DELETE FROM customers WHERE cif = 'C06'")
    data = client(user="analyst01").get(URL).json()["data"]
    assert data[2]["cif"] == "C06"
    assert data[2]["customer"] is None


@pytest.mark.parametrize("user", ["analyst01", "supervisor01"])
def test_ac6_empty_before_any_screening(schema: Any, client: Any, user: str) -> None:
    before = audit_total(schema)
    r = client(user=user).get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    assert body["meta"]["run_id"] is None
    assert body["meta"]["as_of"] is None
    assert body["meta"]["total"] == 0
    assert body["meta"]["counts"] == {"ALERT": 0, "REVIEW": 0, "AUTO_CLEARED": 0}
    assert audit_total(schema) == before
