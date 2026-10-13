"""AC8 of specs/ui-foundation.md: static files, SPA fallback, `aml ui`, wrappers, web/ sources."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import get_settings

from .helpers import ROOT, WEB, aml_cli, error_of

BADGE = "Dữ liệu mẫu"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """DIST: a built SPA stand-in."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html><body>aml-spa</body></html>", encoding="utf-8")
    (root / "assets" / "app.js").write_text('console.log("aml")', encoding="utf-8")
    return root


@pytest.fixture
def ui_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[..., None]:
    """Point `aml ui` at a DuckDB-only configuration with the given overrides."""

    def apply(**env: str) -> None:
        monkeypatch.setenv("DB_BACKEND", "duckdb")
        monkeypatch.setenv("AML__DB__DUCKDB_PATH", str(tmp_path / "ui.duckdb"))
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()

    return apply


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.append(kw))
    return calls


def test_ac8_static_files_and_spa_fallback(schema: Any, client: Any, dist: Path) -> None:
    c = client(AML__UI__DIST_DIR=dist.as_posix())
    root = c.get("/")
    assert root.status_code == 200
    assert root.headers["content-type"].startswith("text/html")
    assert "aml-spa" in root.text
    asset = c.get("/assets/app.js")
    assert asset.status_code == 200
    assert 'console.log("aml")' in asset.text
    for path in ("/cases/C-C01-20260302", "/metrics"):
        r = c.get(path)
        assert r.status_code == 200, path
        assert "aml-spa" in r.text, path


def test_ac8_api_paths_never_fall_back_to_spa(schema: Any, client: Any, dist: Path) -> None:
    c = client(AML__UI__DIST_DIR=dist.as_posix())
    r = c.get("/api/v1/nope")
    assert r.status_code == 404
    assert error_of(r)["code"] == "not_found"
    assert "aml-spa" not in r.text
    assert c.get("/api/v1/health").status_code == 200


def test_ac8_path_traversal_does_not_leak_files(schema: Any, client: Any, dist: Path) -> None:
    r = client(AML__UI__DIST_DIR=dist.as_posix()).get("/%2e%2e/config.yaml")
    assert "seed: 42" not in r.text


def test_ac8_missing_dist_gives_json_404(schema: Any, client: Any, tmp_path: Path) -> None:
    c = client(AML__UI__DIST_DIR=(tmp_path / "nope").as_posix())
    r = c.get("/")
    assert r.status_code == 404
    assert error_of(r)["code"] == "not_found"
    assert "web UI is not built" in error_of(r)["message"]
    assert c.get("/api/v1/health").status_code == 200


def test_ac8_aml_ui_starts_uvicorn_with_config(
    dist: Path, ui_env: Callable[..., None], uvicorn_calls: list[dict[str, Any]]
) -> None:
    ui_env(AML__UI__DIST_DIR=dist.as_posix())
    r = aml_cli("ui")
    assert r.exit_code == 0, r.output
    assert len(uvicorn_calls) == 1
    assert uvicorn_calls[0]["host"] == "127.0.0.1"
    assert uvicorn_calls[0]["port"] == 8000
    line = next(ln for ln in r.stdout.splitlines() if "ui http://127.0.0.1:8000" in ln)
    assert "backend=duckdb" in line
    assert "mock=sample" in line


def test_ac8_aml_ui_host_port_options(
    dist: Path, ui_env: Callable[..., None], uvicorn_calls: list[dict[str, Any]]
) -> None:
    ui_env(AML__UI__DIST_DIR=dist.as_posix())
    r = aml_cli("ui", "--host", "0.0.0.0", "--port", "8123")
    assert r.exit_code == 0, r.output
    assert len(uvicorn_calls) == 1
    assert uvicorn_calls[0]["host"] == "0.0.0.0"
    assert uvicorn_calls[0]["port"] == 8123


def test_ac8_aml_ui_reports_no_mock_flags(
    dist: Path, ui_env: Callable[..., None], uvicorn_calls: list[dict[str, Any]]
) -> None:
    ui_env(AML__UI__DIST_DIR=dist.as_posix(), AML__UI__MOCK__SAMPLE="false")
    r = aml_cli("ui")
    assert r.exit_code == 0, r.output
    line = next(ln for ln in r.stdout.splitlines() if "ui http://" in ln)
    assert "mock=none" in line


def test_ac8_aml_ui_without_dist_fails(
    tmp_path: Path, ui_env: Callable[..., None], uvicorn_calls: list[dict[str, Any]]
) -> None:
    ui_env(AML__UI__DIST_DIR=(tmp_path / "nope").as_posix())
    r = aml_cli("ui")
    assert r.exit_code == 1
    assert "npm --prefix web run build" in r.stderr
    assert "--api-only" in r.stderr
    assert uvicorn_calls == []


def test_ac8_aml_ui_api_only_without_dist(
    tmp_path: Path, ui_env: Callable[..., None], uvicorn_calls: list[dict[str, Any]]
) -> None:
    ui_env(AML__UI__DIST_DIR=(tmp_path / "nope").as_posix())
    r = aml_cli("ui", "--api-only")
    assert r.exit_code == 0, r.output
    assert len(uvicorn_calls) == 1
    assert "dist=none" in r.stdout


def test_ac8_cli_help_and_other_stubs() -> None:
    assert re.search(r"\bui\b", aml_cli("--help").stdout)
    h = aml_cli("ui", "--help")
    assert h.exit_code == 0
    assert "--api-only" in h.stdout
    assert "Phase 9" not in h.stdout
    rag = aml_cli("rag")
    assert rag.exit_code == 1
    assert "arrives in Phase 8" in rag.stderr


def _make_ui_block() -> str:
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if re.match(r"ui\s*:", ln))
    block = [lines[start]]
    for ln in lines[start + 1 :]:
        if ln.startswith(("\t", " ")) or not ln.strip() or block[-1].endswith("\\"):
            block.append(ln)
        else:
            break
    return "\n".join(block)


def test_ac8_wrappers_build_before_ui() -> None:
    block = _make_ui_block()
    assert "npm --prefix web run build" in block
    assert "$(AML) ui" in block
    assert '"--prefix", "web", "run", "build"' in (ROOT / "tasks.ps1").read_text(encoding="utf-8")


def test_ac8_web_package_and_vite_config() -> None:
    pkg_text = (WEB / "package.json").read_text(encoding="utf-8")
    scripts = json.loads(pkg_text)["scripts"]
    assert "dev" in scripts
    assert "build" in scripts
    for banned in ("vitest", "@testing-library", "jsdom"):
        assert banned not in pkg_text
    assert (WEB / "package-lock.json").is_file()
    vite = (WEB / "vite.config.ts").read_text(encoding="utf-8")
    assert '"/api"' in vite
    assert "http://127.0.0.1:8000" in vite


def _web_sources() -> list[Path]:
    files = [p for p in (WEB / "src").rglob("*") if p.is_file()]
    assert files, "web/src has no files"
    return files


def test_ac8_pages_do_not_call_fetch() -> None:
    pages = [p for p in _web_sources() if "pages" in p.relative_to(WEB / "src").parts]
    assert pages, "web/src/pages has no files"
    assert [p.name for p in pages if "fetch(" in p.read_text(encoding="utf-8")] == []


def test_ac8_no_dangerously_set_inner_html() -> None:
    bad = [p.name for p in _web_sources() if "dangerouslySetInnerHTML" in p.read_text("utf-8")]
    assert bad == []


def test_ac8_sample_badge_text_only_in_source_badge() -> None:
    holders = [
        p.relative_to(WEB).as_posix() for p in _web_sources() if BADGE in p.read_text("utf-8")
    ]
    assert holders == ["src/components/SourceBadge.tsx"]
