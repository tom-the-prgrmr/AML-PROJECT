"""AC5 of specs/ui-foundation.md: server-side PII masking on GET /api/v1/cases/{id}/subjects."""

from __future__ import annotations

from typing import Any

from .helpers import CASE_C01_A, audit_rows, count, error_of, mod

URL = f"/api/v1/cases/{CASE_C01_A}/subjects"
RAW = ("B1234561", "B1234562", "Nguyen Thi")


def test_ac5_analyst_gets_masked_subjects(api_mini: Any, client: Any) -> None:
    before = count(api_mini, "audit_log")
    r = client(user="analyst01").get(URL)
    body = r.json()
    assert r.status_code == 200
    assert body["source"] == "live"
    assert body["meta"] == {"pii": "masked"}
    subjects = body["data"]
    assert [s["cif"] for s in subjects] == ["C01", "C02"]
    expected = set(mod("aml.dba.masking").MASKED_COLUMNS)
    for s in subjects:
        assert set(s) == expected
    assert not {"dob", "street", "address", "device_id", "ip"} & set(subjects[0])
    c01 = subjects[0]
    assert c01["full_name"] == "Nguyen T. C."
    assert c01["id_number"] == "****4561"
    assert c01["birth_year"] == 1990
    assert c01["kyc_risk"] == "LOW"
    for raw in RAW:
        assert raw not in r.text
    assert count(api_mini, "audit_log") == before


def test_ac5_client_cannot_unmask(api_mini: Any, client: Any) -> None:
    c = client(user="analyst01")
    for kw in (
        {"params": {"masked": "false"}},
        {"params": {"pii": "full"}},
        {"headers": {"X-AML-Role": "supervisor"}},
    ):
        body = c.get(URL, **kw).json()
        assert body["meta"]["pii"] == "masked"
        assert body["data"][0]["id_number"] == "****4561"


def test_ac5_supervisor_gets_full_subjects_and_one_audit_row(api_mini: Any, client: Any) -> None:
    r = client(user="supervisor01").get(URL)
    body = r.json()
    assert r.status_code == 200
    assert body["meta"] == {"pii": "full"}
    c01 = body["data"][0]
    assert c01["full_name"] == "Nguyen Thi C01"
    assert c01["id_number"] == "B1234561"
    assert c01["dob"] == "1990-01-01"
    rows = audit_rows(api_mini, "module = 'ui'")
    assert len(rows) == 1
    row = rows[0]
    assert row["entity_type"] == "case"
    assert row["entity_id"] == CASE_C01_A
    assert row["decision"] == "PII_VIEWED"
    assert row["actor"] == "supervisor01"
    assert row["version"] == "api/v1"
    assert row["reason"] == (
        f"unmasked subject data of case {CASE_C01_A} shown to supervisor01 (role supervisor)"
    )
    assert row["details"]["cifs"] == ["C01", "C02"]


def test_ac5_unknown_case_is_404_and_not_audited(api_mini: Any, client: Any) -> None:
    before = count(api_mini, "audit_log")
    r = client(user="supervisor01").get("/api/v1/cases/C-NOPE-20260101/subjects")
    assert r.status_code == 404
    assert error_of(r)["code"] == "not_found"
    assert "unknown case_id" in error_of(r)["message"]
    assert count(api_mini, "audit_log") == before


def test_ac5_unknown_user_gets_no_names(api_mini: Any, client: Any) -> None:
    r = client(user="nobody").get(URL)
    assert r.status_code == 401
    assert "Nguyen" not in r.text
