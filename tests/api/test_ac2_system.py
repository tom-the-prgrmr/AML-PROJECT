"""AC2 of specs/ui-foundation.md: system endpoints, error envelope, layering rules."""

from __future__ import annotations

import re
from typing import Any

from aml.common.db import ServiceUnavailableError

from .helpers import API_SRC, FakeDb, api_settings, error_of, make_client, mod


def test_ac2_health_envelope(schema: Any, client: Any) -> None:
    r = client().get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {
        "source": "live",
        "feature": "health",
        "data": {"status": "ok", "backend": "duckdb", "version": "api/v1"},
        "meta": {},
    }
    assert r.headers["X-AML-Source"] == "live"


def test_ac2_status_without_case_run(schema: Any, client: Any) -> None:
    r = client().get("/api/v1/status")
    body = r.json()
    assert r.status_code == 200
    assert body["source"] == "live"
    assert body["feature"] == "status"
    assert body["data"] == {
        "backend": "duckdb",
        "profile": "small",
        "seed": 42,
        "reference_date": "2026-06-30",
        "mock": {"sample": True},
        "case_run": None,
    }


def test_ac2_status_with_case_run(api_mini: Any, client: Any) -> None:
    data = client().get("/api/v1/status").json()["data"]
    assert data["case_run"] == {"run_id": 1, "as_of": "2026-06-30", "cases": 5}


def test_ac2_unknown_endpoint_is_json_404(schema: Any, client: Any) -> None:
    r = client().get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "no such endpoint: /api/v1/nope"}}
    assert "detail" not in r.json()
    assert "X-AML-Source" not in r.headers


def test_ac2_wrong_method_is_405(schema: Any, client: Any) -> None:
    r = client().post("/api/v1/health")
    assert r.status_code == 405
    assert error_of(r)["code"] == "method_not_allowed"


def test_ac2_unexpected_exception_is_hidden_500() -> None:
    c = make_client(FakeDb(RuntimeError("secret SQL text")), api_settings(), "analyst01")
    assert c.get("/api/v1/health").status_code == 200
    r = c.get("/api/v1/status")
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal_error", "message": "internal error"}}
    assert "secret SQL text" not in r.text


def test_ac2_service_unavailable_is_503() -> None:
    c = make_client(FakeDb(ServiceUnavailableError("Oracle not reachable")), api_settings(), None)
    r = c.get("/api/v1/status")
    assert r.status_code == 503
    assert error_of(r)["code"] == "unavailable"


def test_ac2_create_app_returns_distinct_apps(schema: Any) -> None:
    create_app = mod("aml.api.app").create_app
    settings = api_settings()
    assert create_app(settings, db=schema) is not create_app(settings, db=schema)


def test_ac2_no_driver_imports_in_api_package() -> None:
    files = list(API_SRC.rglob("*.py"))
    assert files, "src/aml/api has no python files"
    pattern = re.compile(r"import duckdb|import oracledb|import neo4j|from neo4j")
    assert [f.name for f in files if pattern.search(f.read_text(encoding="utf-8"))] == []


def test_ac2_routers_contain_no_sql() -> None:
    files = list((API_SRC / "routers").rglob("*.py"))
    assert files, "src/aml/api/routers has no python files"
    bad = [f.name for f in files if re.search(r"SELECT|query_df", f.read_text(encoding="utf-8"))]
    assert bad == []
