"""AC4 of specs/ui-live-pages.md: GET /api/v1/trace/methods and aml.graph.availability."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict
from typing import Any

import pytest

from aml.common.config import load_settings

from .helpers import api_settings, make_client, mod
from .live_helpers import OFFLINE, V1, audit_total

URL = f"{V1}/trace/methods"
META = {
    "backend": "duckdb",
    "default_method": "cte_raw",
    "default_hops": 3,
    "default_hours": 72,
    "max_hops": 6,
    "max_hours": 720,
}
KEYS = ["method", "label", "exact", "uses_filters", "available", "reason"]
CTE_RAW = {
    "method": "cte_raw",
    "label": "CTE (raw transactions)",
    "exact": True,
    "uses_filters": False,
    "available": True,
    "reason": None,
}
CTE_EDGE = {
    "method": "cte_edge",
    "label": "CTE (daily edges, approximate)",
    "exact": False,
    "uses_filters": True,
    "available": True,
    "reason": None,
}
PGQ = {
    "method": "pgq",
    "label": "SQL property graph (Oracle)",
    "exact": True,
    "uses_filters": False,
    "available": False,
    "reason": "method pgq is Oracle only; backend is duckdb",
}


@pytest.fixture
def restore_neo4j_method() -> Iterator[None]:
    trace = mod("aml.graph.trace")
    original = trace.METHODS["neo4j"]
    yield
    trace.register_method(original)


def _fake_neo4j(prepare: Any) -> Any:
    from dataclasses import replace

    return replace(mod("aml.graph.trace").METHODS["neo4j"], prepare=prepare)


def test_ac4_endpoint_shape_and_values(schema: Any, client: Any) -> None:
    before = audit_total(schema)
    r = client(**OFFLINE).get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "live"
    assert body["feature"] == "trace"
    assert body["meta"] == META
    data = body["data"]
    assert [m["method"] for m in data] == ["cte_raw", "cte_edge", "pgq", "neo4j"]
    for m in data:
        assert sorted(m) == sorted(KEYS)
    assert data[0] == CTE_RAW
    assert data[1] == CTE_EDGE
    assert data[2] == PGQ
    neo = data[3]
    assert neo["label"] == "Neo4j (Cypher)"
    assert neo["available"] is False
    assert "no bolt listener at bolt://127.0.0.1:1" in neo["reason"]
    assert audit_total(schema) == before


def test_ac4_business_function_returns_same_values(schema: Any) -> None:
    avail = mod("aml.graph.availability")
    result = avail.trace_methods(schema, api_settings(**OFFLINE))
    assert isinstance(result, tuple)
    assert len(result) == 4
    assert all(isinstance(m, avail.MethodAvailability) for m in result)
    as_dicts = [asdict(m) for m in result]
    assert as_dicts[:3] == [CTE_RAW, CTE_EDGE, PGQ]
    assert as_dicts[3]["label"] == "Neo4j (Cypher)"
    assert as_dicts[3]["available"] is False
    assert "no bolt listener at bolt://127.0.0.1:1" in as_dicts[3]["reason"]


def test_ac4_neo4j_up_but_graph_not_synced(
    schema: Any, monkeypatch: pytest.MonkeyPatch, restore_neo4j_method: None
) -> None:
    from aml.common.services import ServiceStatus
    from aml.graph.model import TraceUnavailableError

    avail, trace = mod("aml.graph.availability"), mod("aml.graph.trace")
    monkeypatch.setattr(avail, "neo4j_status", lambda *a, **k: ServiceStatus("neo4j", True, "ok"))

    def stale(db: Any, settings: Any) -> None:
        raise TraceUnavailableError("graph not synced: run aml graph sync")

    trace.register_method(_fake_neo4j(stale))
    neo = avail.trace_methods(schema, api_settings())[3]
    assert neo.available is False
    assert neo.reason == "graph not synced: run aml graph sync"


def test_ac4_neo4j_up_and_synced(
    schema: Any, monkeypatch: pytest.MonkeyPatch, restore_neo4j_method: None
) -> None:
    from aml.common.services import ServiceStatus

    avail, trace = mod("aml.graph.availability"), mod("aml.graph.trace")
    monkeypatch.setattr(avail, "neo4j_status", lambda *a, **k: ServiceStatus("neo4j", True, "ok"))
    trace.register_method(_fake_neo4j(lambda db, settings: None))
    neo = avail.trace_methods(schema, api_settings())[3]
    assert neo.available is True
    assert neo.reason is None


def test_ac4_oracle_configured_but_fell_back_to_duckdb(schema: Any) -> None:
    settings = load_settings(
        environ={"DB_BACKEND": "oracle", "AML__DB__ORACLE__PORT": "1", **OFFLINE}
    )
    r = make_client(schema, settings).get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["backend"] == "duckdb"
    pgq = body["data"][2]
    assert pgq["method"] == "pgq"
    assert pgq["available"] is False
    assert pgq["reason"].startswith("oracle not available:")
    assert "no listener on localhost:1" in pgq["reason"]
