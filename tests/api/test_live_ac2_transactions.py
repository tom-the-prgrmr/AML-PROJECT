"""AC2 of specs/ui-live-pages.md: GET /api/v1/cases/{case_id}/transactions."""

from __future__ import annotations

from typing import Any

import pytest

from .helpers import audit_rows
from .live_helpers import (
    CASE_A,
    CASE_C05,
    MEMO,
    NAME,
    NOPE,
    V1,
    assert_error,
    audit_total,
    set_memo_and_name,
)

URL = f"{V1}/cases/{CASE_A}/transactions"
KEYS = [
    "txn_id",
    "txn_ts",
    "from_account_id",
    "to_account_id",
    "amount_vnd",
    "channel",
    "memo",
    "counterparty_name",
    "item_keys",
    "memo_key",
    "memo_category",
    "memo_method",
]
T01 = {
    "txn_id": "T01",
    "txn_ts": "2026-03-02T09:00:00",
    "from_account_id": None,
    "to_account_id": "A01",
    "amount_vnd": 390000000,
    "channel": "CASH",
    "memo": None,
    "counterparty_name": None,
    "item_keys": ["STRUCTURING|A01|2026-03-02T09:00:00"],
    "memo_key": None,
    "memo_category": None,
    "memo_method": None,
}
MASKED = {"pii": "masked", "total": 6, "limit": 50, "offset": 0}


def test_ac2_analyst_view(api_mini: Any, client: Any) -> None:
    set_memo_and_name(api_mini)
    before = audit_total(api_mini)
    r = client(user="analyst01").get(URL)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["feature"] == "cases"
    assert body["meta"] == MASKED
    data = body["data"]
    assert [t["txn_id"] for t in data] == ["T01", "T02", "T03", "T04", "T05", "T06"]
    for t in data:
        assert sorted(t) == sorted(KEYS)
        assert not any(k.endswith("_html") for k in t)
    assert data[0] == T01
    assert data[1]["item_keys"] == ["NET_CYCLE|A01>A03>A04|2026-03-05T10:00:00"]
    t05 = data[4]
    assert isinstance(t05["memo"], str)
    assert t05["memo"] == MEMO
    assert t05["counterparty_name"] == "Tran V. <."
    assert "Tran Van" not in r.text
    assert audit_total(api_mini) == before


@pytest.mark.parametrize("suffix", ["?masked=false", "?pii=full"])
def test_ac2_analyst_cannot_unmask_by_query(api_mini: Any, client: Any, suffix: str) -> None:
    set_memo_and_name(api_mini)
    body = client(user="analyst01").get(URL + suffix).json()
    assert body["meta"]["pii"] == "masked"
    assert body["data"][4]["counterparty_name"] == "Tran V. <."


def test_ac2_pagination(api_mini: Any, client: Any) -> None:
    body = client(user="analyst01").get(URL + "?limit=2&offset=4").json()
    assert [t["txn_id"] for t in body["data"]] == ["T05", "T06"]
    assert body["meta"] == {"pii": "masked", "total": 6, "limit": 2, "offset": 4}


@pytest.mark.parametrize("suffix", ["?limit=0", "?offset=-1"])
def test_ac2_bad_paging_is_422(api_mini: Any, client: Any, suffix: str) -> None:
    assert_error(client(user="analyst01").get(URL + suffix), 422, "invalid_request")


def test_ac2_supervisor_sees_full_and_one_audit_row(api_mini: Any, client: Any) -> None:
    set_memo_and_name(api_mini)
    before = audit_total(api_mini)
    r = client(user="supervisor01").get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["pii"] == "full"
    t05 = body["data"][4]
    assert t05["counterparty_name"] == NAME
    assert t05["memo"] == MEMO
    assert audit_total(api_mini) == before + 1
    rows = audit_rows(api_mini, "decision = 'PII_VIEWED'")
    assert len(rows) == 1
    row = rows[0]
    assert row["module"] == "ui"
    assert row["entity_type"] == "case"
    assert row["entity_id"] == CASE_A
    assert row["actor"] == "supervisor01"
    assert row["version"] == "api/v1"
    assert row["reason"] == (
        "unmasked transaction data of case C-C01-20260302 shown to supervisor01 (role supervisor)"
    )
    assert row["details"] == {"transactions": 6}


@pytest.mark.parametrize("user", ["analyst01", "supervisor01"])
def test_ac2_screening_only_case_has_no_transactions(api_mini: Any, client: Any, user: str) -> None:
    before = audit_total(api_mini)
    r = client(user=user).get(f"{V1}/cases/{CASE_C05}/transactions")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0
    assert audit_total(api_mini) == before


def test_ac2_unknown_case_is_404(api_mini: Any, client: Any) -> None:
    assert_error(client(user="analyst01").get(f"{V1}/cases/{NOPE}/transactions"), 404, "not_found")
