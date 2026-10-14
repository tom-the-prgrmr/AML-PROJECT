"""AC6 of specs/ui-memo-relabel.md: POST /memos/{memo_key}/relabel, every wrong call."""

from __future__ import annotations

from typing import Any

import pytest

from aml.memo.classify import MemoError

from .helpers import api_settings, count, make_client, mod
from .live_helpers import assert_error
from .memo_helpers import GOOD, K_LOAN, MODEL, api_memo, relabel_url, state

BAD_BODIES = [
    {**GOOD, "category": "clean"},
    {**GOOD, "reason": ""},
    {**GOOD, "reason": "   "},
    {"category": "other"},
    {**GOOD, "reason": "x" * 501},
    {**GOOD, "actor": "boss"},
]


@pytest.mark.parametrize("body", BAD_BODIES, ids=lambda b: str(sorted(b.items()))[:60])
def test_ac6_bad_body_is_422_and_writes_nothing(api_mini: Any, client: Any, body: dict) -> None:
    api_memo(api_mini)
    before = state(api_mini)
    r = client(user="analyst01").post(relabel_url(K_LOAN), json=body)
    assert_error(r, 422, "invalid_request")
    assert "Traceback" not in r.text
    assert state(api_mini) == before


def test_ac6_not_json_is_422(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    before = state(api_mini)
    r = client(user="analyst01").post(relabel_url(K_LOAN), content=b"x")
    assert_error(r, 422, "invalid_request")
    assert state(api_mini) == before


def test_ac6_unknown_key_is_404(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    before = state(api_mini)
    r = client(user="analyst01").post(relabel_url("0" * 32), json=GOOD)
    assert_error(r, 404, "not_found", "unknown memo key " + "0" * 32)
    assert state(api_mini) == before


def test_ac6_short_prefix_is_422(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    before = state(api_mini)
    r = client(user="analyst01").post(relabel_url("abc"), json=GOOD)
    assert_error(r, 422, "invalid_request", "memo key prefix must be at least 8 characters")
    assert state(api_mini) == before


def test_ac6_ambiguous_prefix_is_422(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    twin = K_LOAN[:8] + "f" * 24
    api_mini.execute(
        "INSERT INTO memo_classifications (run_id, memo_key, memo_version, llm_model, memo_norm, "
        "category, method, attempts, pattern, transactions, reason, classified_ts) "
        "VALUES (1, ?, 'memo/v1', ?, 'x', 'other', 'LLM', 1, 0, 1, 'x', CURRENT_TIMESTAMP)",
        [twin, MODEL],
    )
    before = state(api_mini)
    r = client(user="analyst01").post(relabel_url(K_LOAN[:8]), json=GOOD)
    assert_error(r, 422, "invalid_request", "ambiguous memo key prefix 341c388f: it matches 2 keys")
    assert state(api_mini) == before


def test_ac6_system_actor_is_403(api_mini: Any) -> None:
    # Settings validation already rejects `system` in ui.users (config.py), so the validator is
    # bypassed with model_copy to reach the router: the 403 is the defence in depth.
    api_memo(api_mini)
    base = api_settings()
    users = {"system": "analyst", "analyst01": "analyst", "supervisor01": "supervisor"}
    settings = base.model_copy(update={"ui": base.ui.model_copy(update={"users": users})})
    before = state(api_mini)
    r = make_client(api_mini, settings, "system").post(relabel_url(K_LOAN), json=GOOD)
    assert r.status_code == 403
    assert r.json() == {
        "error": {
            "code": "forbidden",
            "message": "a relabel needs a human actor, not the system actor",
        }
    }
    assert state(api_mini) == before


@pytest.mark.parametrize("verb", ["delete", "get"])
def test_ac6_other_verbs_are_405(api_mini: Any, client: Any, verb: str) -> None:
    api_memo(api_mini)
    r = getattr(client(user="analyst01"), verb)(relabel_url(K_LOAN))
    assert_error(r, 405, "method_not_allowed")


def test_ac6_unknown_user_is_401(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    before = state(api_mini)
    r = client(user="nobody").post(relabel_url(K_LOAN), json=GOOD)
    assert_error(r, 401, "unknown_user")
    assert state(api_mini) == before


def test_ac6_8d_behaviour_unchanged(api_mini: Any) -> None:
    api_memo(api_mini)
    with pytest.raises(MemoError, match="a relabel needs a human actor"):
        mod("aml.memo.relabel").relabel_memo(
            api_mini, api_settings(), K_LOAN, "other", reason="x", actor="system"
        )
    assert count(api_mini, "memo_overrides") == 0
