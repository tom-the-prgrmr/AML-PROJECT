"""AC7 of specs/ui-foundation.md: per-feature mock mechanism and the `source` flag."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from .helpers import API_SRC, PREFIX, ROOT, api_settings, mod

FIXTURE = ROOT / "src" / "aml" / "api" / "fixtures" / "sample.json"
SAMPLE_DATA = {
    "items": [
        {"id": "S-001", "label": "sample row 1", "value": 42},
        {"id": "S-002", "label": "sample row 2", "value": 7},
    ]
}
NOTICE = "Sample data - not a measured result"


def _paths(c: Any) -> list[str]:
    return sorted(
        r.path
        for r in c.app.routes
        if r.path.startswith(PREFIX)
        and "GET" in (getattr(r, "methods", None) or ())
        and "{" not in r.path
    )


def test_ac7_sample_is_mock_with_notice(schema: Any, client: Any) -> None:
    c = client()
    r = c.get("/api/v1/sample")
    assert r.status_code == 200
    assert r.json() == {
        "source": "mock",
        "feature": "sample",
        "data": SAMPLE_DATA,
        "meta": {"mock": {"fixture": "sample.json", "notice": NOTICE}},
    }
    assert r.headers["X-AML-Source"] == "mock"
    assert r.json()["data"] == json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert c.get("/api/v1/sample").content == r.content


def test_ac7_flag_off_without_live_fn_is_501(schema: Any, client: Any) -> None:
    c = client(AML__UI__MOCK__SAMPLE="false")
    r = c.get("/api/v1/sample")
    assert r.status_code == 501
    assert r.json() == {
        "error": {
            "code": "not_implemented",
            "message": "feature 'sample' has no live implementation and ui.mock.sample is off",
        }
    }
    assert "S-001" not in r.text
    assert c.get("/api/v1/status").json()["data"]["mock"] == {"sample": False}


def test_ac7_flag_off_with_live_fn_is_live() -> None:
    settings = api_settings(AML__UI__MOCK__SAMPLE="false")
    r = mod("aml.api.mock").mock_or_live(settings, "sample", lambda: {"items": []})
    assert json.loads(r.body) == {
        "source": "live",
        "feature": "sample",
        "data": {"items": []},
        "meta": {},
    }
    assert r.headers["X-AML-Source"] == "live"


def test_ac7_flag_on_never_calls_live_fn() -> None:
    def boom() -> Any:
        raise AssertionError("live_fn must not be called")

    r = mod("aml.api.mock").mock_or_live(api_settings(), "sample", boom)
    assert json.loads(r.body)["source"] == "mock"
    assert r.headers["X-AML-Source"] == "mock"


def test_ac7_unknown_feature_is_value_error() -> None:
    with pytest.raises(ValueError, match="unknown mock feature 'nope'"):
        mod("aml.api.mock").mock_or_live(api_settings(), "nope", None)


def test_ac7_mock_fields_match_fixtures() -> None:
    fields = set(mod("aml.common.config").MockConfig.model_fields)
    assert fields == set(mod("aml.api.mock").features()) == {"sample"}


def test_ac7_only_sample_route_is_mock_by_default(schema: Any, client: Any) -> None:
    c = client()
    paths = _paths(c)
    assert "/api/v1/sample" in paths
    mocked = set()
    for path in paths:
        r = c.get(path)
        assert r.status_code == 200, path
        source = r.json()["source"]
        assert source in ("live", "mock"), path
        assert r.headers["X-AML-Source"] == source, path
        if source == "mock":
            mocked.add(path)
    assert mocked == {"/api/v1/sample"}


def test_ac7_no_mock_when_all_flags_off(schema: Any, client: Any) -> None:
    fields = mod("aml.common.config").MockConfig.model_fields
    env = {f"AML__UI__MOCK__{name.upper()}": "false" for name in fields}
    c = client(**env)
    for path in _paths(c):
        r = c.get(path)
        assert r.headers.get("X-AML-Source") != "mock", path
        assert r.status_code == 501 or r.json()["source"] != "mock", path


def test_ac7_fixtures_only_referenced_by_mock_module() -> None:
    files = list(API_SRC.rglob("*.py"))
    assert files, "src/aml/api has no python files"
    bad = [
        f.name
        for f in files
        if f.name != "mock.py" and re.search("fixtures", f.read_text(encoding="utf-8"))
    ]
    assert bad == []
