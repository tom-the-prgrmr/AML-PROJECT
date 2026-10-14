"""AC1 of specs/ui-live-pages.md: GET /api/v1/cases/{case_id}."""

from __future__ import annotations

from typing import Any

from .live_helpers import CASE_A, CASE_B, CASE_C03, NOPE, V1, assert_error, audit_total

KEYS = [
    "case_id",
    "run_id",
    "golden_customer_id",
    "status",
    "window_start",
    "first_alert_ts",
    "last_alert_ts",
    "reason",
    "alerts",
    "enrichment",
    "disposition",
]
ALERT_KEYS = [
    "item_key",
    "source",
    "rule_id",
    "alert_ref",
    "cif",
    "event_ts",
    "end_ts",
    "amount_vnd",
    "reason",
]
FIRST_ALERT = {
    "item_key": "STRUCTURING|A01|2026-03-02T09:00:00",
    "source": "RULE",
    "rule_id": "STRUCTURING",
    "alert_ref": "1",
    "cif": "C01",
    "event_ts": "2026-03-02T09:00:00",
    "end_ts": "2026-03-02T09:00:00",
    "amount_vnd": 390000000,
    "reason": "STRUCTURING on A01",
}


def test_ac1_envelope_and_top_level_keys(api_mini: Any, client: Any) -> None:
    r = client(user="analyst01").get(f"{V1}/cases/{CASE_A}")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "live"
    assert body["feature"] == "cases"
    assert body["meta"] == {}
    data = body["data"]
    assert sorted(data) == sorted(KEYS)
    assert "subjects" not in data
    assert "score" not in data
    assert data["run_id"] == 1
    assert data["golden_customer_id"] == "G-C01"
    assert data["status"] == "OPEN"
    assert data["window_start"] == "2026-03-02T09:00:00"
    assert data["last_alert_ts"] == "2026-04-20T12:00:00"
    assert data["disposition"] is None


def test_ac1_alerts_order_and_first_alert(api_mini: Any, client: Any) -> None:
    alerts = client(user="analyst01").get(f"{V1}/cases/{CASE_A}").json()["data"]["alerts"]
    assert [a["item_key"] for a in alerts] == [
        "STRUCTURING|A01|2026-03-02T09:00:00",
        "NET_CYCLE|A01>A03>A04|2026-03-05T10:00:00",
        "RAPID_MOVEMENT|A02|2026-04-20T08:00:00",
    ]
    for a in alerts:
        assert sorted(a) == sorted(ALERT_KEYS)
    assert alerts[0] == FIRST_ALERT


def test_ac1_enrichment_blocks(api_mini: Any, client: Any) -> None:
    enr = client(user="analyst01").get(f"{V1}/cases/{CASE_A}").json()["data"]["enrichment"]
    assert list(enr) == ["kyc", "linked_cifs", "dq_issues", "txn_summary", "network", "history"]
    assert enr["kyc"]["risk_rating"] == "HIGH"
    assert enr["linked_cifs"]["cifs"] == ["C01", "C02"]
    assert enr["dq_issues"]["customer"] == [
        {"cif": "C02", "rule_id": "KYC_OCCUPATION_MISSING", "dimension": "COMPLETENESS"}
    ]
    ts = enr["txn_summary"]
    assert ts["window_start"] == "2026-01-21"
    assert ts["txn_count"] == 5
    assert ts["in_vnd"] == 1170000000
    assert ts["cash_in_vnd"] == 390000000
    net = enr["network"]
    assert net["source"] == "none"
    assert net["counterparties"][0] == {
        "account_id": "EXT-01",
        "golden_customer_id": None,
        "direction": "IN",
        "txns": 1,
        "vnd": 500000000,
    }
    assert net["shared_alert_cases"] == [CASE_C03, "C-C04-20260305"]
    assert enr["history"]["prior_cases"] == []


def test_ac1_same_bytes_for_both_roles_no_pii_no_audit(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    a = client(user="analyst01").get(f"{V1}/cases/{CASE_A}")
    s = client(user="supervisor01").get(f"{V1}/cases/{CASE_A}")
    assert a.status_code == s.status_code == 200
    assert a.content == s.content
    for needle in ("Nguyen", "B123456", "4561"):
        assert needle not in a.text
    assert audit_total(api_mini) == before


def test_ac1_history_lists_prior_case_with_screening_alert(api_mini: Any, client: Any) -> None:
    data = client(user="analyst01").get(f"{V1}/cases/{CASE_B}").json()["data"]
    assert data["alerts"][1]["rule_id"] == "SCREENING_ALERT"
    assert data["enrichment"]["history"]["prior_cases"] == [
        {
            "case_id": CASE_A,
            "first_alert_ts": "2026-03-02T09:00:00",
            "alerts": 3,
            "disposition": None,
            "decided_on": None,
        }
    ]


def test_ac1_disposition_shown_separately_from_status(api_mini: Any, client: Any) -> None:
    c = client(user="analyst01")
    post = c.post(
        f"{V1}/cases/{CASE_C03}/disposition",
        json={"disposition": "SUSPICIOUS", "reason": "layering through A03"},
    )
    assert post.status_code == 201
    data = c.get(f"{V1}/cases/{CASE_C03}").json()["data"]
    assert data["status"] == "OPEN"
    assert data["disposition"] == {
        "disposition_id": 1,
        "disposition": "SUSPICIOUS",
        "reason": "layering through A03",
        "actor": "analyst01",
        "origin": "HUMAN",
        "decided_on": "2026-06-30",
        "run_id": 1,
    }


def test_ac1_unknown_case_is_404(api_mini: Any, client: Any) -> None:
    r = client(user="analyst01").get(f"{V1}/cases/{NOPE}")
    assert_error(r, 404, "not_found", "unknown case_id")


def test_ac1_no_case_run_yet_is_404(schema: Any, client: Any) -> None:
    r = client(user="analyst01").get(f"{V1}/cases/{CASE_A}")
    assert_error(r, 404, "not_found")
