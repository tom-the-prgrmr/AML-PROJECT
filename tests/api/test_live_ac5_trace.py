"""AC5 of specs/ui-live-pages.md: GET /api/v1/accounts/{account_id}/trace."""

from __future__ import annotations

from typing import Any

import pytest

from .helpers import audit_rows
from .live_helpers import OFFLINE, V1, assert_error, audit_total

URL = f"{V1}/accounts/A01/trace"
PATH_KEYS = [
    "hop",
    "path",
    "account_id",
    "step_path",
    "first_ts",
    "last_ts",
    "amount_vnd",
    "is_cycle",
]
EXPECTED = [
    (1, "A01>A03", "T02", 300000000, False),
    (1, "A01>EXT-03", "T07", 50000000, False),
    (2, "A01>A03>A04", "T02>T03", 290000000, False),
    (3, "A01>A03>A04>A01", "T02>T03>T04", 280000000, True),
]
META = {
    "method": "cte_raw",
    "backend": "duckdb",
    "exact": True,
    "account_id": "A01",
    "hops": 3,
    "hours": 72,
    "since": None,
    "min_amount_vnd": 0,
    "top_k": 0,
    "n_paths": 4,
    "n_accounts": 3,
    "n_cycles": 1,
    "query_lines": 38,
    "total": 4,
    "limit": 50,
    "offset": 0,
}


def test_ac5_paths_meta_and_privacy(api_mini: Any, client: Any) -> None:
    r = client(user="analyst01").get(URL + "?hops=3&hours=72")
    assert r.status_code == 200
    body = r.json()
    assert body["feature"] == "trace"
    data = body["data"]
    assert len(data) == 4
    for p in data:
        assert sorted(p) == sorted(PATH_KEYS)
    assert [
        (p["hop"], p["path"], p["step_path"], p["amount_vnd"], p["is_cycle"]) for p in data
    ] == (EXPECTED)
    last = data[-1]
    assert last["account_id"] == "A01"
    assert last["first_ts"] == "2026-03-05T10:00:00"
    assert last["last_ts"] == "2026-03-07T10:00:00"
    meta = dict(body["meta"])
    seconds = meta.pop("seconds")
    assert isinstance(seconds, float)
    assert seconds >= 0
    assert meta == META
    assert '"full_name"' not in r.text
    assert '"cif"' not in r.text
    assert "Nguyen" not in r.text


def test_ac5_writes_exactly_one_traced_audit_row(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    assert client(user="analyst01").get(URL + "?hops=3&hours=72").status_code == 200
    assert audit_total(api_mini) == before + 1
    rows = audit_rows(api_mini, "decision = 'TRACED'")
    assert len(rows) == 1
    row = rows[0]
    assert row["module"] == "graph"
    assert row["entity_type"] == "account"
    assert row["entity_id"] == "A01"
    assert row["actor"] == "analyst01"
    assert row["version"] == "trace/cte_raw"
    assert row["reason"] == (
        "cte_raw on duckdb: followed money out of A01 up to 3 hops within 72 hours; "
        "found 4 paths to 3 accounts, 1 hops closing a cycle"
    )


def test_ac5_audit_actor_follows_request_user(api_mini: Any, client: Any) -> None:
    assert client(user="supervisor01").get(URL + "?hops=3&hours=72").status_code == 200
    rows = audit_rows(api_mini, "decision = 'TRACED'")
    assert [r["actor"] for r in rows] == ["supervisor01"]


def test_ac5_defaults_give_same_paths(api_mini: Any, client: Any) -> None:
    body = client(user="analyst01").get(URL).json()
    assert [p["path"] for p in body["data"]] == [e[1] for e in EXPECTED]
    assert body["meta"]["hops"] == 3
    assert body["meta"]["hours"] == 72


def test_ac5_paging(api_mini: Any, client: Any) -> None:
    body = client(user="analyst01").get(URL + "?hops=3&hours=72&limit=2&offset=2").json()
    assert [p["path"] for p in body["data"]] == ["A01>A03>A04", "A01>A03>A04>A01"]
    assert body["meta"]["n_paths"] == 4
    assert body["meta"]["limit"] == 2
    assert body["meta"]["offset"] == 2


def test_ac5_since_filter(api_mini: Any, client: Any) -> None:
    body = client(user="analyst01").get(URL + "?since=2026-05-01T00:00:00").json()
    assert [p["path"] for p in body["data"]] == ["A01>EXT-03"]
    assert body["meta"]["since"] == "2026-05-01T00:00:00"


def test_ac5_other_accounts(api_mini: Any, client: Any) -> None:
    c = client(user="analyst01")
    a02 = c.get(f"{V1}/accounts/A02/trace").json()["data"]
    assert [(p["path"], p["amount_vnd"]) for p in a02] == [("A02>EXT-02", 480000000)]
    r = c.get(f"{V1}/accounts/ZZZ/trace")
    assert r.status_code == 200
    assert r.json()["data"] == []
    assert r.json()["meta"]["n_paths"] == 0


def test_ac5_cte_edge_meta_defaults(api_mini: Any, client: Any) -> None:
    r = client(user="analyst01").get(URL + "?method=cte_edge")
    assert r.status_code == 200
    meta = r.json()["meta"]
    assert meta["method"] == "cte_edge"
    assert meta["exact"] is False
    assert meta["min_amount_vnd"] == 10000000
    assert meta["top_k"] == 5


@pytest.mark.parametrize(
    ("suffix", "status", "code", "text"),
    [
        ("?method=nope", 422, "invalid_request", "unknown method 'nope'"),
        ("?hops=7", 422, "invalid_request", "hops must be between 1 and 6, got 7"),
        ("?hours=0", 422, "invalid_request", None),
        ("?hops=abc", 422, "invalid_request", None),
        ("?limit=0", 422, "invalid_request", None),
    ],
)
def test_ac5_invalid_requests_write_nothing(
    api_mini: Any, client: Any, suffix: str, status: int, code: str, text: str | None
) -> None:
    before = audit_total(api_mini)
    r = client(user="analyst01").get(URL + suffix)
    assert_error(r, status, code, text)
    assert "data" not in r.json()
    assert audit_total(api_mini) == before


def test_ac5_pgq_on_duckdb_is_503(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    r = client(user="analyst01").get(URL + "?method=pgq")
    assert r.status_code == 503
    assert r.json() == {
        "error": {"code": "unavailable", "message": "method pgq is Oracle only; backend is duckdb"}
    }
    assert audit_total(api_mini) == before


def test_ac5_neo4j_offline_is_503(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    r = client(user="analyst01", **OFFLINE).get(URL + "?method=neo4j")
    assert_error(r, 503, "unavailable", "neo4j not available")
    assert "data" not in r.json()
    assert audit_total(api_mini) == before


def test_ac5_too_many_paths_is_422(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    r = client(user="analyst01", AML__TRACE__MAX_PATHS="2").get(URL + "?hops=3&hours=72")
    assert_error(r, 422, "invalid_request", "returned more than 2 paths")
    assert audit_total(api_mini) == before
