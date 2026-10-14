"""Follow-ups to the 9a / 9b reviews that no AC test pins: 404s around the SPA, error texts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from .helpers import error_of
from .live_helpers import V1, assert_error


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html><body>aml-spa</body></html>", encoding="utf-8")
    (root / "assets" / "app.js").write_text('console.log("aml")', encoding="utf-8")
    return root


def test_api_without_trailing_slash_is_a_json_404(schema: Any, client: Any, dist: Path) -> None:
    r = client(AML__UI__DIST_DIR=dist.as_posix()).get("/api")
    assert r.status_code == 404
    assert error_of(r)["code"] == "not_found"
    assert "aml-spa" not in r.text


def test_missing_build_asset_is_a_404_not_the_page(schema: Any, client: Any, dist: Path) -> None:
    c = client(AML__UI__DIST_DIR=dist.as_posix())
    r = c.get("/assets/index-old.js")
    assert r.status_code == 404
    assert error_of(r) == {"code": "not_found", "message": "no such file: /assets/index-old.js"}
    assert c.get("/assets/app.js").status_code == 200
    # a SPA route that merely looks like a path still gets the page
    assert "aml-spa" in c.get("/screening").text


def test_dq_trend_runs_error_names_runs(schema: Any, client: Any) -> None:
    r = client(user="analyst01").get(f"{V1}/dq/trend?runs=0")
    assert_error(r, 422, "invalid_request", "runs must be between 1 and")
