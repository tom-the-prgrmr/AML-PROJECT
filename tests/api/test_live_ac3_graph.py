"""AC3 of specs/ui-live-pages.md: GET /api/v1/cases/{case_id}/graph (SQL source, no Neo4j)."""

from __future__ import annotations

from typing import Any

from .helpers import audit_rows
from .live_helpers import (
    CASE_A,
    CASE_C04,
    CASE_C05,
    NOPE,
    OFFLINE,
    V1,
    assert_error,
    audit_total,
)

URL = f"{V1}/cases/{CASE_A}/graph"
NODE_KEYS = ["id", "type", "label", "is_subject", "golden_customer_id", "cif", "cifs"]
EDGE_KEYS = ["id", "type", "source", "target", "txns", "vnd", "first_ts", "last_ts"]
NODE_IDS = ["G-C01", "G-C03", "G-C04", "A01", "A02", "A03", "A04", "EXT-01", "EXT-02"]
EDGE_IDS = [
    "owns:G-C01>A01",
    "owns:G-C01>A02",
    "owns:G-C03>A03",
    "owns:G-C04>A04",
    "transfer:A01>A03",
    "transfer:A02>EXT-02",
    "transfer:A03>A04",
    "transfer:A04>A01",
    "transfer:EXT-01>A02",
]
META = {
    "pii": "masked",
    "graph_source": "sql",
    "backend": "duckdb",
    "window_start": "2026-01-21",
    "window_end": "2026-04-20",
    "counterparties": {"total": 4, "shown": 4},
    "truncated": False,
}


def by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {i["id"]: i for i in items}


def test_ac3_analyst_graph(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    r = client(user="analyst01", **OFFLINE).get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["feature"] == "graph"
    assert body["meta"] == META
    assert sorted(body["data"]) == ["edges", "nodes"]
    nodes, edges = body["data"]["nodes"], body["data"]["edges"]
    assert [n["id"] for n in nodes] == NODE_IDS
    for n in nodes:
        assert sorted(n) == sorted(NODE_KEYS)
    for e in edges:
        assert sorted(e) == sorted(EDGE_KEYS)
    n = by_id(nodes)
    assert n["G-C01"] == {
        "id": "G-C01",
        "type": "customer",
        "label": "G-C01",
        "is_subject": True,
        "golden_customer_id": "G-C01",
        "cif": None,
        "cifs": [
            {"cif": "C01", "full_name": "Nguyen T. C."},
            {"cif": "C02", "full_name": "Nguyen T. C."},
        ],
    }
    assert n["A01"] == {
        "id": "A01",
        "type": "account",
        "label": "A01",
        "is_subject": True,
        "golden_customer_id": "G-C01",
        "cif": "C01",
        "cifs": None,
    }
    assert n["A03"]["is_subject"] is False
    assert n["A03"]["golden_customer_id"] == "G-C03"
    assert n["EXT-01"] == {
        "id": "EXT-01",
        "type": "external_account",
        "label": "EXT-01",
        "is_subject": False,
        "golden_customer_id": None,
        "cif": None,
        "cifs": None,
    }
    assert [e["id"] for e in edges] == EDGE_IDS
    e = by_id(edges)
    assert e["transfer:A01>A03"] == {
        "id": "transfer:A01>A03",
        "type": "transfer",
        "source": "A01",
        "target": "A03",
        "txns": 1,
        "vnd": 300000000,
        "first_ts": "2026-03-05T10:00:00",
        "last_ts": "2026-03-05T10:00:00",
    }
    assert e["owns:G-C01>A01"] == {
        "id": "owns:G-C01>A01",
        "type": "owns",
        "source": "G-C01",
        "target": "A01",
        "txns": None,
        "vnd": None,
        "first_ts": None,
        "last_ts": None,
    }
    ids = set(n)
    assert all(x["source"] in ids and x["target"] in ids for x in edges)
    assert "Nguyen Thi" not in r.text
    assert "B123456" not in r.text
    assert audit_total(api_mini) == before


def test_ac3_supervisor_sees_names_and_audit_row(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    r = client(user="supervisor01", **OFFLINE).get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["pii"] == "full"
    g = by_id(body["data"]["nodes"])["G-C01"]
    assert g["cifs"] == [
        {"cif": "C01", "full_name": "Nguyen Thi C01"},
        {"cif": "C02", "full_name": "Nguyen Thi C02"},
    ]
    assert audit_total(api_mini) == before + 1
    rows = audit_rows(api_mini, "decision = 'PII_VIEWED'")
    assert len(rows) == 1
    row = rows[0]
    assert row["module"] == "ui"
    assert row["entity_type"] == "case"
    assert row["entity_id"] == CASE_A
    assert row["actor"] == "supervisor01"
    assert row["reason"] == (
        "unmasked graph data of case C-C01-20260302 shown to supervisor01 (role supervisor)"
    )
    assert row["details"]["cifs"] == ["C01", "C02", "C03", "C04"]


def test_ac3_counterparty_cap_truncates(api_mini: Any, client: Any) -> None:
    c = client(user="analyst01", AML__UI__GRAPH_MAX_COUNTERPARTIES="2", **OFFLINE)
    body = c.get(URL).json()
    assert [n["id"] for n in body["data"]["nodes"]] == ["G-C01", "A01", "A02", "EXT-01", "EXT-02"]
    assert [e["id"] for e in body["data"]["edges"]] == [
        "owns:G-C01>A01",
        "owns:G-C01>A02",
        "transfer:A02>EXT-02",
        "transfer:EXT-01>A02",
    ]
    assert body["meta"]["counterparties"] == {"total": 4, "shown": 2}
    assert body["meta"]["truncated"] is True


def test_ac3_case_without_transfers(api_mini: Any, client: Any) -> None:
    body = client(user="analyst01", **OFFLINE).get(f"{V1}/cases/{CASE_C05}/graph").json()
    assert [n["id"] for n in body["data"]["nodes"]] == ["G-C05", "A05"]
    assert [e["id"] for e in body["data"]["edges"]] == ["owns:G-C05>A05"]
    assert body["meta"]["counterparties"] == {"total": 0, "shown": 0}


def test_ac3_edges_between_counterparties_are_kept(api_mini: Any, client: Any) -> None:
    body = client(user="analyst01", **OFFLINE).get(f"{V1}/cases/{CASE_C04}/graph").json()
    edge_ids = {e["id"] for e in body["data"]["edges"]}
    assert {"transfer:A01>A03", "transfer:A03>A04", "transfer:A04>A01"} <= edge_ids


def test_ac3_unknown_case_is_404(api_mini: Any, client: Any) -> None:
    r = client(user="analyst01", **OFFLINE).get(f"{V1}/cases/{NOPE}/graph")
    assert_error(r, 404, "not_found")
