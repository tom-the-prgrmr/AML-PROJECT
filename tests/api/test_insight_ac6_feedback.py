"""AC6 of specs/ui-mock-pages.md: POST /api/v1/assistant/feedback and ``record_feedback``."""

from __future__ import annotations

from typing import Any

import pytest

from tests.assistant.an_helpers import LLM, R4, S_AMOUNT, S_OK1, S_OK2, J

from .helpers import api_settings, audit_rows, count, mod
from .insight_helpers import ANSWER_ID, C1, V1, Q, fakes
from .live_helpers import assert_error, audit_total

CHAT = f"{V1}/assistant/chat"
URL = f"{V1}/assistant/feedback"
GOOD = {"answer_id": ANSWER_ID, "rating": "down", "comment": "câu 2 sai số tiền"}


def _answered(db: Any, client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    fakes(monkeypatch, llm=LLM(J(S_OK1, S_AMOUNT, S_OK2)), retriever=R4())
    r = client(user="analyst01").post(CHAT, json={"case_id": C1, "question": Q})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["answer_id"] == ANSWER_ID


def _rated(db: Any) -> list[dict[str, Any]]:
    return audit_rows(db, "decision = 'ANSWER_RATED'")


def test_ac6_feedback_is_recorded_with_one_audit_row(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answered(api_mini, client, monkeypatch)
    before = audit_total(api_mini)
    r = client(user="analyst01").post(URL, json=GOOD)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["source"] == "live"
    assert body["feature"] == "assistant"
    assert body["data"] == {"answer_id": ANSWER_ID, "rating": "down", "actor": "analyst01"}
    assert audit_total(api_mini) == before + 1
    (row,) = _rated(api_mini)
    assert row["module"] == "assistant"
    assert row["entity_type"] == "answer"
    assert row["entity_id"] == ANSWER_ID
    assert row["decision"] == "ANSWER_RATED"
    assert row["reason"] == f"answer {ANSWER_ID} rated down by analyst01"
    assert row["version"] == "feedback/v1"
    assert row["actor"] == "analyst01"
    assert row["details"] == {
        "answer_id": ANSWER_ID,
        "rating": "down",
        "comment": "câu 2 sai số tiền",
    }


def test_ac6_rating_again_appends_a_row_and_blank_comment_is_null(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answered(api_mini, client, monkeypatch)
    client(user="analyst01").post(URL, json=GOOD)
    r = client(user="supervisor01").post(
        URL, json={"answer_id": ANSWER_ID, "rating": "up", "comment": "   "}
    )
    assert r.status_code == 201, r.text
    first, second = _rated(api_mini)
    assert first["details"]["rating"] == "down"
    assert second["details"]["comment"] is None
    assert second["actor"] == "supervisor01"


def test_ac6_unknown_answer_id_is_404(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answered(api_mini, client, monkeypatch)
    before = audit_total(api_mini)
    body = {"answer_id": "ans-000000000000", "rating": "up", "comment": None}
    r = client(user="analyst01").post(URL, json=body)
    assert_error(r, 404, "not_found")
    assert r.json()["error"]["message"] == "unknown answer_id ans-000000000000"
    assert audit_total(api_mini) == before


def test_ac6_failed_answer_cannot_be_rated(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch, llm=LLM("nope", "nope again"), retriever=R4())
    r = client(user="analyst01").post(CHAT, json={"case_id": C1, "question": Q})
    assert r.status_code == 502, r.text
    (failed,) = audit_rows(api_mini, "decision = 'FAILED'")
    failed_id = failed["details"]["answer_id"]
    before = audit_total(api_mini)
    r = client(user="analyst01").post(
        URL, json={"answer_id": failed_id, "rating": "down", "comment": None}
    )
    assert_error(r, 404, "not_found")
    assert audit_total(api_mini) == before


@pytest.mark.parametrize(
    "body",
    [
        {"answer_id": ANSWER_ID, "rating": "meh", "comment": None},
        {"answer_id": "x", "rating": "up", "comment": None},
        {"answer_id": ANSWER_ID, "rating": "up", "comment": "c" * 1001},
        {"rating": "up", "comment": None},
        {"answer_id": ANSWER_ID, "rating": "up", "comment": None, "actor": "boss"},
    ],
    ids=["rating", "answer_id_shape", "comment_too_long", "missing_answer_id", "actor_field"],
)
def test_ac6_bad_bodies_are_422_and_write_nothing(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]
) -> None:
    _answered(api_mini, client, monkeypatch)
    before = audit_total(api_mini)
    assert_error(client(user="analyst01").post(URL, json=body), 422, "invalid_request")
    assert audit_total(api_mini) == before


def test_ac6_feedback_does_not_touch_cases(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answered(api_mini, client, monkeypatch)
    before = (count(api_mini, "case_dispositions"), count(api_mini, "cases"))
    client(user="analyst01").post(URL, json=GOOD)
    client(user="analyst01").post(URL, json={**GOOD, "answer_id": "ans-000000000000"})
    assert (count(api_mini, "case_dispositions"), count(api_mini, "cases")) == before


def test_ac6_record_feedback_rejects_system_actor(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answered(api_mini, client, monkeypatch)
    fb = mod("aml.assistant.feedback")
    settings = api_settings()
    before = audit_total(api_mini)
    with pytest.raises(fb.FeedbackError, match="feedback needs a human actor"):
        fb.record_feedback(
            api_mini,
            settings,
            ANSWER_ID,
            "up",
            comment=None,
            actor=settings.audit.system_actor,
        )
    assert audit_total(api_mini) == before
