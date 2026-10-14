"""AC2 of specs/ui-memo-relabel.md: the three memo columns of GET /cases/{id}/transactions."""

from __future__ import annotations

from typing import Any

from tests.memo.helpers import MEMOS

from .helpers import audit_rows, count
from .live_helpers import assert_error
from .memo_helpers import (
    C5,
    K_CRY,
    K_INJ,
    K_LOAN,
    K_SAL,
    KEYS12,
    NOPE,
    TXN,
    UNTOUCHED,
    V1,
    api_memo,
    tables,
    tri,
)
from .test_live_ac2_transactions import MASKED, T01


def test_ac2_analyst_columns(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    before_audit = count(api_mini, "audit_log")
    before = tables(api_mini, UNTOUCHED)
    r = client(user="analyst01").get(TXN)
    assert r.status_code == 200
    body = r.json()
    assert body["feature"] == "cases"
    assert body["meta"] == MASKED
    data = body["data"]
    assert [t["txn_id"] for t in data] == ["T01", "T02", "T03", "T04", "T05", "T06"]
    for t in data:
        assert sorted(t) == sorted(KEYS12)
    assert data[0]["memo"] is None
    assert tri(data[0]) == (None, None, None)
    assert data[0] == {**T01}
    assert tri(data[1]) == (K_LOAN, "loan_repayment", "LLM")
    assert tri(data[2]) == (K_LOAN, "loan_repayment", "LLM")
    assert data[1]["memo"] == "Trả nợ vay bạn bè"
    assert data[2]["memo"] == "  Trả  nợ vay bạn bè "
    assert tri(data[3]) == (K_SAL, "salary", "LLM")
    assert tri(data[4]) == (K_INJ, "suspicious_wording", "RULE")
    assert data[4]["memo"] == MEMOS["T05"]
    assert tri(data[5]) == (K_CRY, "crypto_like", "LLM")
    assert count(api_mini, "audit_log") == before_audit
    assert tables(api_mini, UNTOUCHED) == before


def test_ac2_supervisor_same_columns_and_one_pii_row(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    analyst = client(user="analyst01").get(TXN).json()["data"]
    before = count(api_mini, "audit_log")
    r = client(user="supervisor01").get(TXN)
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["pii"] == "full"
    assert [tri(t) for t in body["data"]] == [tri(t) for t in analyst]
    assert all(sorted(t) == sorted(KEYS12) for t in body["data"])
    assert count(api_mini, "audit_log") == before + 1
    assert len(audit_rows(api_mini, "decision = 'PII_VIEWED'")) == 1


def test_ac2_pagination_keeps_12_keys(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    body = client(user="analyst01").get(TXN + "?limit=2&offset=1").json()
    assert [t["txn_id"] for t in body["data"]] == ["T02", "T03"]
    assert all(sorted(t) == sorted(KEYS12) for t in body["data"])


def test_ac2_screening_only_case_and_unknown_case(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    c = client(user="analyst01")
    r = c.get(f"{V1}/cases/{C5}/transactions")
    assert r.status_code == 200
    assert r.json()["data"] == []
    assert_error(c.get(f"{V1}/cases/{NOPE}/transactions"), 404, "not_found")
