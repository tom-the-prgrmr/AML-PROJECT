"""AC10 of specs/ui-live-pages.md: config, auth on every new route, layering and import rules."""

from __future__ import annotations

import ast
import subprocess
import sys
from typing import Any

import pytest
from pydantic import ValidationError

from aml.common.config import MockConfig, load_settings

from .helpers import API_SRC, ROOT, mod
from .live_helpers import CASE_A, OFFLINE, V1, audit_total

FIVE = [
    f"{V1}/trace/methods",
    f"{V1}/screening/hits",
    f"{V1}/dq/results",
    f"{V1}/dq/trend",
    f"{V1}/benchmark",
]
OTHERS_GET = [
    f"{V1}/cases/{CASE_A}",
    f"{V1}/cases/{CASE_A}/transactions",
    f"{V1}/cases/{CASE_A}/graph",
    f"{V1}/accounts/A01/trace",
]
REVIEW_URL = f"{V1}/screening/hits/C05/WL2/review"
REVIEW_BODY = {"decision": "FALSE_MATCH", "reason": "different year of birth"}
ALLOWED_CASES_NAMES = {"load_case", "record_disposition", "CaseError", "DISPOSITIONS"}


def _call_all(c: Any) -> list[Any]:
    out = [c.get(p) for p in FIVE + OTHERS_GET]
    out.append(c.post(REVIEW_URL, json=REVIEW_BODY))
    return out


def test_ac10_graph_max_counterparties_default() -> None:
    assert load_settings(environ={}).ui.graph_max_counterparties == 50


@pytest.mark.parametrize("value", ["0", "501"])
def test_ac10_graph_max_counterparties_range(value: str) -> None:
    with pytest.raises(
        ValidationError, match="ui graph_max_counterparties must be between 1 and 500"
    ):
        load_settings(environ={"AML__UI__GRAPH_MAX_COUNTERPARTIES": value})


def test_ac10_five_paths_are_live(schema: Any, client: Any) -> None:
    c = client(**OFFLINE)
    for path in FIVE:
        r = c.get(path)
        assert r.status_code == 200, path
        assert r.json()["source"] == "live", path
        assert r.headers["X-AML-Source"] == "live", path


def test_ac10_no_mock_flag_for_new_features() -> None:
    forbidden = {"cases", "graph", "trace", "screening", "dq", "benchmark"}
    assert not (set(MockConfig.model_fields) & forbidden)


def test_ac10_unknown_user_is_401_everywhere(schema: Any, client: Any) -> None:
    responses = _call_all(client(user="nobody", **OFFLINE))
    assert len(responses) == 10
    for r in responses:
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unknown_user"


def test_ac10_missing_user_is_401_everywhere_and_audit_unchanged(
    api_mini: Any, client: Any
) -> None:
    before = audit_total(api_mini)
    responses = _call_all(client(AML__UI__DEFAULT_USER="", **OFFLINE))
    assert len(responses) == 10
    for r in responses:
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "missing_user"
    assert audit_total(api_mini) == before


def test_ac10_business_modules_do_not_import_fastapi() -> None:
    code = (
        "import sys, aml.screening.review, aml.graph.availability; "
        "sys.exit(1 if 'fastapi' in sys.modules else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("needle", ["audit(", "neo4j_status", "oracle_status"])
def test_ac10_routers_stay_thin(needle: str) -> None:
    files = sorted((API_SRC / "routers").rglob("*.py"))
    assert files
    offenders = [f.name for f in files if needle in f.read_text(encoding="utf-8")]
    assert offenders == []


def test_ac10_api_only_uses_allowed_case_names() -> None:
    bad: list[str] = []
    for path in sorted(API_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("aml.cases"):
                names = {a.name for a in node.names}
                if not names <= ALLOWED_CASES_NAMES:
                    bad.append(f"{path.name}: {sorted(names - ALLOWED_CASES_NAMES)}")
            elif isinstance(node, ast.Import):
                bad.extend(
                    f"{path.name}: import {a.name}"
                    for a in node.names
                    if a.name.startswith("aml.cases")
                )
    assert bad == []


def test_ac10_methods_registry_order_after_importing_app() -> None:
    mod("aml.api.app")
    assert list(mod("aml.graph.trace").METHODS) == ["cte_raw", "cte_edge", "pgq", "neo4j"]
