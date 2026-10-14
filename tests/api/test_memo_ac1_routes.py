"""AC1 of specs/ui-memo-relabel.md: the two new routes, empty state, identity, no mock flag."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from aml.common.config import MockConfig

from .helpers import ROOT, count
from .live_helpers import assert_error
from .memo_helpers import (
    GOOD,
    K_LOAN,
    MODEL,
    TXN,
    V1,
    api_memo,
    relabel_url,
)

MEMOS_URL = f"{V1}/memos"
EMPTY_META = {"total": 0, "limit": 50, "offset": 0, "memo_version": "memo/v1", "llm_model": MODEL}


def _route_set(c: Any) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for r in c.app.routes:
        for m in getattr(r, "methods", None) or ():
            out.add((m, r.path))
    return out


def test_ac1_exactly_two_new_routes(schema: Any, client: Any) -> None:
    routes = _route_set(client())
    memo_routes = {(m, p) for m, p in routes if p.startswith(f"{V1}/memos")}
    assert ("GET", MEMOS_URL) in memo_routes
    assert ("POST", f"{V1}/memos/{{memo_key}}/relabel") in memo_routes
    assert {p for _, p in memo_routes} == {MEMOS_URL, f"{V1}/memos/{{memo_key}}/relabel"}
    assert {m for m, _ in memo_routes} - {"HEAD"} == {"GET", "POST"}


def test_ac1_get_memos_empty_on_schema(schema: Any, client: Any) -> None:
    r = client(user="analyst01").get(MEMOS_URL)
    assert r.status_code == 200
    assert r.headers["X-AML-Source"] == "live"
    body = r.json()
    assert body["source"] == "live"
    assert body["feature"] == "memos"
    assert body["data"] == []
    assert body["meta"] == EMPTY_META


def test_ac1_no_mock_flag_for_memos() -> None:
    assert set(MockConfig.model_fields) == {"sample"}


def test_ac1_ac7_mock_suite_still_green() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/api/test_ac7_mock.py",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:]


def _calls(c: Any) -> list[Any]:
    return [c.get(MEMOS_URL), c.post(relabel_url(K_LOAN), json=GOOD), c.get(TXN)]


def test_ac1_unknown_user_is_401_everywhere(schema: Any, client: Any) -> None:
    before = count(schema, "audit_log")
    responses = _calls(client(user="nobody"))
    assert len(responses) == 3
    for r in responses:
        assert_error(r, 401, "unknown_user")
    assert count(schema, "audit_log") == before


def test_ac1_missing_user_is_401_everywhere(schema: Any, client: Any) -> None:
    before = count(schema, "audit_log")
    responses = _calls(client(AML__UI__DEFAULT_USER=""))
    assert len(responses) == 3
    for r in responses:
        assert_error(r, 401, "missing_user")
    assert count(schema, "audit_log") == before


def test_ac1_relabel_unknown_key_on_schema_is_404(schema: Any, client: Any) -> None:
    before = count(schema, "audit_log")
    r = client(user="analyst01").post(relabel_url(K_LOAN), json=GOOD)
    assert_error(r, 404, "not_found", f"unknown memo key {K_LOAN}")
    assert count(schema, "audit_log") == before
    assert count(schema, "memo_overrides") == 0


def test_ac1_ac2_reads_with_labels_do_not_write(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    before = count(api_mini, "audit_log")
    c = client(user="analyst01")
    assert c.get(MEMOS_URL).status_code == 200
    assert c.get(TXN).status_code == 200
    assert count(api_mini, "audit_log") == before
    assert count(api_mini, "memo_overrides") == 0
