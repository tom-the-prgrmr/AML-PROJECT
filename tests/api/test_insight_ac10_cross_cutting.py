"""AC10 of specs/ui-mock-pages.md: read-only GETs, layering, import rules and web conventions."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from .helpers import API_SRC, ROOT, WEB, count
from .insight_helpers import C1, V1, fakes, read_text, text_files

SRC = ROOT / "src" / "aml"
WEB_SRC = WEB / "src"
GET_URLS = [
    f"{V1}/cases/scores",
    f"{V1}/cases/{C1}/summary",
    f"{V1}/cases/{C1}/typologies",
    f"{V1}/metrics/funnel",
    f"{V1}/metrics/detections",
    f"{V1}/metrics/below-the-line/auto-cleared",
    f"{V1}/metrics/suppression",
]
TABLES = ("audit_log", "cases", "case_alerts", "case_dispositions", "case_runs", "case_scores")
WEB_SUFFIXES = (".ts", ".tsx", ".css", ".json", ".html")


def _contains(files: list[Path], needle: str) -> list[str]:
    return [str(f.relative_to(ROOT)) for f in files if needle in read_text(f)]


def _py(directory: Path) -> list[Path]:
    files = sorted(directory.rglob("*.py"))
    assert files, f"no python files under {directory}"
    return files


def test_ac10_get_routes_change_no_table(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch)
    before = {t: count(api_mini, t) for t in TABLES}
    for user in ("analyst01", "supervisor01"):
        c = client(user=user)
        for url in GET_URLS:
            assert c.get(url).status_code == 200, url
    assert {t: count(api_mini, t) for t in TABLES} == before


def test_ac10_pure_modules_do_not_load_fastapi() -> None:
    code = (
        "import sys, aml.metrics, aml.assistant.feedback; "
        "sys.exit(1 if 'fastapi' in sys.modules else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("needle", ["aml.api", "audit(", "insert_df", ".execute(", "run_script"])
def test_ac10_metrics_package_is_read_only(needle: str) -> None:
    assert _contains(_py(SRC / "metrics"), needle) == []


@pytest.mark.parametrize("needle", ["audit(", "record_disposition", "run_cases"])
def test_ac10_routers_stay_thin(needle: str) -> None:
    assert _contains(_py(API_SRC / "routers"), needle) == []


@pytest.mark.parametrize("needle", ["record_disposition", "run_cases", "disposition", "status ="])
def test_ac10_assistant_adapter_cannot_decide(needle: str) -> None:
    files = [API_SRC / "routers" / "assistant.py", API_SRC / "assistant.py"]
    for f in files:
        assert f.is_file(), f
    assert _contains(files, needle) == []


def test_ac10_no_leftover_mock_layer() -> None:
    assert sorted(p.name for p in (API_SRC / "fixtures").iterdir()) == ["sample.json"]
    for name in ("live.py", "contracts.py", "sse.py"):
        assert not (API_SRC / name).exists(), name
    assert not (API_SRC / "mockdata").exists()


def test_ac10_markdown_dependencies() -> None:
    pkg = json.loads(read_text(WEB / "package.json"))
    deps = pkg["dependencies"]
    assert "react-markdown" in deps
    assert "remark-gfm" in deps
    everything = {**deps, **pkg.get("devDependencies", {})}
    assert "rehype-raw" not in everything


def test_ac10_only_markdown_component_imports_react_markdown() -> None:
    files = text_files(WEB_SRC, WEB_SUFFIXES)
    found = {Path(p).name for p in _contains(files, "react-markdown")}
    assert found == {"Markdown.tsx"}


@pytest.mark.parametrize("needle", ["dangerouslySetInnerHTML", "innerHTML", "rehype-raw"])
def test_ac10_web_has_no_raw_html_paths(needle: str) -> None:
    assert _contains(text_files(WEB_SRC, WEB_SUFFIXES), needle) == []


@pytest.mark.parametrize("needle", ["fetch(", "EventSource"])
def test_ac10_pages_do_not_talk_to_the_network_directly(needle: str) -> None:
    pages = text_files(WEB_SRC / "pages", WEB_SUFFIXES)
    assert pages
    assert _contains(pages, needle) == []


def test_ac10_sample_banner_text_lives_in_source_badge_only() -> None:
    found = {Path(p).name for p in _contains(text_files(WEB_SRC, WEB_SUFFIXES), "Dữ liệu mẫu")}
    assert found == {"SourceBadge.tsx"}


@pytest.mark.parametrize(
    "testid", ["slot-case-score", "slot-case-summary", "slot-assistant", "graph-highlight-missing"]
)
def test_ac10_test_ids_still_present(testid: str) -> None:
    assert _contains(text_files(WEB_SRC, WEB_SUFFIXES), testid) != []


def test_ac10_highlight_hook_used_by_a_new_case_panel() -> None:
    case_dir = WEB_SRC / "pages" / "case"
    others = [
        f
        for f in text_files(case_dir, WEB_SUFFIXES)
        if f.name not in ("CaseGraphPanel.tsx", "TracePanel.tsx")
    ]
    assert _contains(others, "useCaseHighlight") != []


@pytest.mark.parametrize(
    "name",
    [
        "CaseScores",
        "Answer",
        "Citation",
        "DraftNarrative",
        "Funnel",
        "DetectionRow",
        "SuppressionMetrics",
    ],
)
def test_ac10_insight_types_declared(name: str) -> None:
    path = WEB_SRC / "api" / "insightTypes.ts"
    assert path.is_file()
    assert re.search(rf"\b{name}\b", read_text(path))
