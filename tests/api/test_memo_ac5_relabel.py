"""AC5 of specs/ui-memo-relabel.md: POST /api/v1/memos/{memo_key}/relabel, the happy path."""

from __future__ import annotations

from typing import Any

from .helpers import audit_rows, count, query
from .memo_helpers import (
    GOOD,
    K_INJ,
    K_LOAN,
    K_SAL,
    MEMOS_URL,
    TXN,
    UNTOUCHED,
    api_memo,
    relabel_url,
    tables,
    tri,
)


def _txn(c: Any) -> dict[str, dict[str, Any]]:
    return {t["txn_id"]: t for t in c.get(TXN).json()["data"]}


def test_ac5_first_relabel_data_audit_and_effect(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    before = tables(api_mini, UNTOUCHED)
    audit_before = count(api_mini, "audit_log")
    analyst = client(user="analyst01")
    r = analyst.post(relabel_url(K_LOAN), json=GOOD)
    assert r.status_code == 201, r.text
    assert r.headers["X-AML-Source"] == "live"
    body = r.json()
    assert body["source"] == "live"
    assert body["feature"] == "memos"
    assert body["data"] == {
        "override_id": 1,
        "memo_key": K_LOAN,
        "category": "suspicious_wording",
        "previous_category": "loan_repayment",
        "previous_method": "LLM",
        "actor": "analyst01",
    }
    assert body["meta"] == {}
    assert count(api_mini, "audit_log") == audit_before + 1
    rows = audit_rows(api_mini, "decision = 'MEMO_RELABELLED'")
    assert len(rows) == 1
    row = rows[0]
    assert (row["module"], row["entity_type"], row["entity_id"]) == ("memo", "memo", K_LOAN)
    assert row["reason"] == "borrower is a known mule collector"
    assert row["version"] == "memo/v1"
    assert row["actor"] == "analyst01"
    assert row["details"] == {
        "override_id": 1,
        "category": "suspicious_wording",
        "previous_category": "loan_repayment",
        "previous_method": "LLM",
        "model_category": "loan_repayment",
        "model_method": "LLM",
    }
    ov = query(api_mini, "SELECT actor FROM memo_overrides")
    assert ov["actor"].tolist() == ["analyst01"]
    assert count(api_mini, "memo_classifications") == 5
    cls = query(
        api_mini,
        f"SELECT category, method FROM memo_classifications WHERE memo_key = '{K_LOAN}'",
    )
    assert cls.to_dict("records") == [{"category": "loan_repayment", "method": "LLM"}]
    txns = _txn(analyst)
    assert tri(txns["T02"]) == (K_LOAN, "suspicious_wording", "HUMAN")
    assert tri(txns["T03"]) == (K_LOAN, "suspicious_wording", "HUMAN")
    assert tri(txns["T04"]) == (K_SAL, "salary", "LLM")
    human = analyst.get(MEMOS_URL + "?method=HUMAN").json()["data"]
    assert human == [
        {
            "memo_key": K_LOAN,
            "memo_norm": "trả nợ vay bạn bè",
            "category": "suspicious_wording",
            "method": "HUMAN",
            "transactions": 2,
            "model_category": "loan_repayment",
            "model_method": "LLM",
        }
    ]
    assert tables(api_mini, UNTOUCHED) == before
    assert count(api_mini, "case_dispositions") == 0


def test_ac5_four_relabels_in_a_row(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    before = tables(api_mini, UNTOUCHED)
    analyst = client(user="analyst01")
    supervisor = client(user="supervisor01")
    assert analyst.post(relabel_url(K_LOAN), json=GOOD).status_code == 201

    r2 = supervisor.post(
        relabel_url(K_LOAN),
        json={"category": "loan_repayment", "reason": "checked the loan contract"},
    )
    assert r2.status_code == 201, r2.text
    d2 = r2.json()["data"]
    assert d2["override_id"] == 2
    assert d2["previous_category"] == "suspicious_wording"
    assert d2["previous_method"] == "HUMAN"
    assert d2["actor"] == "supervisor01"
    assert tri(_txn(analyst)["T02"]) == (K_LOAN, "loan_repayment", "HUMAN")
    first = query(api_mini, "SELECT category, actor FROM memo_overrides WHERE override_id = 1")
    assert first.to_dict("records") == [{"category": "suspicious_wording", "actor": "analyst01"}]

    r3 = analyst.post(
        relabel_url(K_SAL[:8]), json={"category": "salary", "reason": "confirmed payroll"}
    )
    assert r3.status_code == 201, r3.text
    d3 = r3.json()["data"]
    assert d3["memo_key"] == K_SAL
    assert d3["override_id"] == 3
    assert d3["previous_category"] == "salary"
    assert d3["previous_method"] == "LLM"

    long_reason = "x" * 500
    r4 = analyst.post(relabel_url(K_INJ), json={"category": "other", "reason": long_reason})
    assert r4.status_code == 201, r4.text
    assert r4.json()["data"]["previous_method"] == "RULE"
    assert (
        audit_rows(api_mini, f"entity_id = '{K_INJ}' AND decision = 'MEMO_RELABELLED'")[0]["reason"]
        == long_reason
    )

    assert len(audit_rows(api_mini, "decision = 'MEMO_RELABELLED'")) == 4
    assert count(api_mini, "memo_overrides") == 4
    assert tables(api_mini, UNTOUCHED) == before
    assert count(api_mini, "case_dispositions") == 0
