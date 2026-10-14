"""AC7 of specs/ui-live-pages.md: POST /api/v1/screening/hits/{cif}/{entry_id}/review."""

from __future__ import annotations

from typing import Any

import pytest

from .helpers import api_settings, audit_rows, count, mod, query
from .live_helpers import V1, assert_error, audit_total

URL = f"{V1}/screening/hits/C05/WL2/review"
HITS = f"{V1}/screening/hits"
GOOD = {"decision": "FALSE_MATCH", "reason": "different year of birth"}


def test_ac7_post_records_one_audit_row_only(api_mini: Any, client: Any) -> None:
    tables = ("screening_results", "cases", "case_dispositions")
    counts_before = {t: count(api_mini, t) for t in tables}
    before = audit_total(api_mini)
    r = client(user="analyst01").post(URL, json=GOOD)
    assert r.status_code == 201
    assert r.json() == {
        "source": "live",
        "feature": "screening",
        "data": {
            "cif": "C05",
            "entry_id": "WL2",
            "decision": "FALSE_MATCH",
            "reason": "different year of birth",
            "actor": "analyst01",
            "decided_on": "2026-06-30",
            "run_id": 1,
            "system_decision": "REVIEW",
        },
        "meta": {},
    }
    assert audit_total(api_mini) == before + 1
    rows = audit_rows(api_mini, "entity_type = 'screening_match'")
    assert len(rows) == 1
    row = rows[0]
    assert row["module"] == "screening"
    assert row["entity_id"] == "C05:WL2"
    assert row["decision"] == "FALSE_MATCH"
    assert row["actor"] == "analyst01"
    assert row["reason"] == "different year of birth"
    assert row["version"] == "screening/v1"
    assert row["details"] == {
        "run_id": 1,
        "system_decision": "REVIEW",
        "final_score": 80.0,
        "list_type": "PEP",
        "decided_on": "2026-06-30",
        "origin": "HUMAN",
    }
    assert {t: count(api_mini, t) for t in tables} == counts_before
    cur = query(
        api_mini, "SELECT decision FROM screening_current WHERE cif = 'C05' AND entry_id = 'WL2'"
    )
    assert list(cur["decision"]) == ["REVIEW"]


def test_ac7_hits_show_latest_review_next_to_system_decision(api_mini: Any, client: Any) -> None:
    c = client(user="analyst01")
    assert c.post(URL, json=GOOD).status_code == 201
    data = c.get(HITS).json()["data"]
    by_cif = {h["cif"]: h for h in data}
    assert by_cif["C05"]["review"] == {
        "decision": "FALSE_MATCH",
        "reason": "different year of birth",
        "actor": "analyst01",
        "decided_on": "2026-06-30",
    }
    assert by_cif["C05"]["decision"] == "REVIEW"
    assert by_cif["C02"]["review"] is None
    assert by_cif["C06"]["review"] is None


def test_ac7_second_review_supersedes_first_and_both_stay_in_audit(
    api_mini: Any, client: Any
) -> None:
    assert client(user="analyst01").post(URL, json=GOOD).status_code == 201
    r = client(user="supervisor01").post(
        URL, json={"decision": "TRUE_MATCH", "reason": "passport checked"}
    )
    assert r.status_code == 201
    assert r.json()["data"]["actor"] == "supervisor01"
    c05 = next(h for h in client(user="analyst01").get(HITS).json()["data"] if h["cif"] == "C05")
    assert c05["review"]["decision"] == "TRUE_MATCH"
    assert c05["review"]["actor"] == "supervisor01"
    rows = audit_rows(
        api_mini, "entity_id = 'C05:WL2' AND decision IN ('TRUE_MATCH', 'FALSE_MATCH')"
    )
    assert len(rows) == 2


def test_ac7_auto_cleared_hit_can_be_reviewed(api_mini: Any, client: Any) -> None:
    r = client(user="analyst01").post(
        f"{V1}/screening/hits/C06/WL3/review",
        json={"decision": "TRUE_MATCH", "reason": "same person"},
    )
    assert r.status_code == 201
    assert r.json()["data"]["system_decision"] == "AUTO_CLEARED"


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({**GOOD, "actor": "boss"}, 422, "invalid_request"),
        ({**GOOD, "reason": ""}, 422, "invalid_request"),
        ({**GOOD, "reason": "   "}, 422, "invalid_request"),
        ({"decision": "FALSE_MATCH"}, 422, "invalid_request"),
        ({**GOOD, "decision": "CLEARED"}, 422, "invalid_request"),
    ],
)
def test_ac7_rejected_bodies_write_nothing(
    api_mini: Any, client: Any, body: dict[str, Any], status: int, code: str
) -> None:
    before = audit_total(api_mini)
    r = client(user="analyst01").post(URL, json=body)
    assert_error(r, status, code)
    assert audit_total(api_mini) == before


def test_ac7_unknown_hit_is_404(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    r = client(user="analyst01").post(f"{V1}/screening/hits/C01/WL1/review", json=GOOD)
    assert_error(r, 404, "not_found", "unknown screening hit C01:WL1")
    assert audit_total(api_mini) == before


def test_ac7_delete_is_405(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    r = client(user="analyst01").delete(URL)
    assert_error(r, 405, "method_not_allowed")
    assert audit_total(api_mini) == before


def test_ac7_no_identity_is_401(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    r = client(AML__UI__DEFAULT_USER="").post(URL, json=GOOD)
    assert_error(r, 401, "missing_user")
    assert audit_total(api_mini) == before


def test_ac7_record_review_rejects_system_actor(api_mini: Any) -> None:
    review = mod("aml.screening.review")
    with pytest.raises(review.ScreeningReviewError, match="a screening review needs a human actor"):
        review.record_review(
            api_mini, api_settings(), "C05", "WL2", "FALSE_MATCH", reason="x", actor="system"
        )


def test_ac7_record_review_rejects_unknown_decision(api_mini: Any) -> None:
    review = mod("aml.screening.review")
    with pytest.raises(ValueError):
        review.record_review(
            api_mini, api_settings(), "C05", "WL2", "MAYBE", reason="x", actor="analyst01"
        )


def test_ac7_latest_reviews_keeps_newest_per_pair(api_mini: Any, client: Any) -> None:
    review = mod("aml.screening.review")
    assert client(user="analyst01").post(URL, json=GOOD).status_code == 201
    assert (
        client(user="supervisor01")
        .post(URL, json={"decision": "TRUE_MATCH", "reason": "passport checked"})
        .status_code
        == 201
    )
    assert (
        client(user="analyst01")
        .post(
            f"{V1}/screening/hits/C06/WL3/review",
            json={"decision": "TRUE_MATCH", "reason": "same person"},
        )
        .status_code
        == 201
    )
    latest = review.latest_reviews(api_mini)
    assert set(latest) == {("C05", "WL2"), ("C06", "WL3")}
    assert latest[("C05", "WL2")].decision == "TRUE_MATCH"
