"""AC3 of specs/ui-foundation.md: actor / role resolution."""

from __future__ import annotations

from typing import Any

import pytest

from .helpers import api_settings, error_of, mod

ME = "/api/v1/me"
USERS = [
    {"actor": "analyst01", "role": "analyst"},
    {"actor": "supervisor01", "role": "supervisor"},
]


def test_ac3_default_user_is_analyst(schema: Any, client: Any) -> None:
    r = client().get(ME)
    assert r.status_code == 200
    assert r.json()["data"] == {
        "actor": "analyst01",
        "role": "analyst",
        "pii": "masked",
        "users": USERS,
    }


def test_ac3_supervisor_sees_full_pii(schema: Any, client: Any) -> None:
    data = client(user="supervisor01").get(ME).json()["data"]
    assert (data["actor"], data["role"], data["pii"]) == ("supervisor01", "supervisor", "full")


def test_ac3_header_name_is_case_insensitive(schema: Any, client: Any) -> None:
    data = client().get(ME, headers={"x-aml-user": "supervisor01"}).json()["data"]
    assert (data["actor"], data["role"], data["pii"]) == ("supervisor01", "supervisor", "full")


def test_ac3_client_cannot_claim_a_role(schema: Any, client: Any) -> None:
    r = client(user="analyst01").get(
        ME, params={"role": "supervisor"}, headers={"X-AML-Role": "supervisor"}
    )
    assert r.status_code == 200
    assert r.json()["data"]["role"] == "analyst"
    assert r.json()["data"]["pii"] == "masked"


def test_ac3_unknown_user_is_401(schema: Any, client: Any) -> None:
    r = client(user="nobody").get(ME)
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "unknown_user", "message": "unknown user 'nobody'"}}


@pytest.mark.parametrize(
    "path", ["/api/v1/me", "/api/v1/status", "/api/v1/cases", "/api/v1/sample"]
)
def test_ac3_missing_user_is_401_without_default(schema: Any, client: Any, path: str) -> None:
    r = client(AML__UI__DEFAULT_USER="").get(path)
    assert r.status_code == 401
    assert error_of(r)["code"] == "missing_user"
    assert "X-AML-User" in error_of(r)["message"]


def test_ac3_health_needs_no_identity(schema: Any, client: Any) -> None:
    assert client(AML__UI__DEFAULT_USER="").get("/api/v1/health").status_code == 200


def test_ac3_resolve_user() -> None:
    identity = mod("aml.api.identity")
    settings = api_settings()
    assert identity.resolve_user(settings, None) == identity.User("analyst01", "analyst", "masked")
    assert identity.resolve_user(settings, "supervisor01").pii == "full"
