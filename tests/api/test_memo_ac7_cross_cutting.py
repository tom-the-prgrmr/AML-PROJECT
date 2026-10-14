"""AC7 of specs/ui-memo-relabel.md: layering, imports, frozen files, web sources."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import MockConfig

from .helpers import API_SRC, ROOT, WEB, count
from .memo_helpers import MEMOS_URL, TXN, api_memo
from .test_live_ac10_cross_cutting import ALLOWED_CASES_NAMES

BASE_COMMIT = "e71eb63"
ALLOWED_MEMO_NAMES = {
    "relabel_memo",
    "list_labels",
    "Relabel",
    "MAX_REASON",
    "METHODS",
    "MemoError",
    "CATEGORIES",
    "normalize_memo",
    "memo_key",
    "MEMO_VERSION",
}
SIDE_TABLES = (
    "audit_log",
    "memo_overrides",
    "memo_classifications",
    "memo_runs",
    "case_memo_features",
    "cases",
    "case_alerts",
    "case_dispositions",
)


def _api_files() -> list[Path]:
    files = sorted(API_SRC.rglob("*.py"))
    assert files
    return files


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ac7_reads_write_nothing(api_mini: Any, client: Any) -> None:
    api_memo(api_mini)
    before = {t: count(api_mini, t) for t in SIDE_TABLES}
    analyst = client(user="analyst01")
    assert analyst.get(MEMOS_URL).status_code == 200
    assert analyst.get(TXN).status_code == 200
    assert client(user="supervisor01").get(MEMOS_URL).status_code == 200
    after = {t: count(api_mini, t) for t in SIDE_TABLES}
    assert after == before
    sup = client(user="supervisor01").get(TXN)
    assert sup.status_code == 200
    final = {t: count(api_mini, t) for t in SIDE_TABLES}
    assert final.pop("audit_log") == before["audit_log"] + 1  # PII_VIEWED only
    assert final == {k: v for k, v in before.items() if k != "audit_log"}


def test_ac7_memo_modules_do_not_import_fastapi() -> None:
    code = (
        "import sys, aml.memo.relabel, aml.memo.normalize, aml.memo.store; "
        "sys.exit(1 if 'fastapi' in sys.modules else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert proc.returncode == 0, proc.stderr


def test_ac7_api_only_uses_allowed_memo_names() -> None:
    bad: list[str] = []
    for path in _api_files():
        for node in ast.walk(ast.parse(_text(path))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("aml.memo"):
                names = {a.name for a in node.names}
                if not names <= ALLOWED_MEMO_NAMES:
                    bad.append(f"{path.name}: {sorted(names - ALLOWED_MEMO_NAMES)}")
            elif isinstance(node, ast.Import):
                bad.extend(
                    f"{path.name}: import {a.name}"
                    for a in node.names
                    if a.name.startswith("aml.memo")
                )
    assert bad == []


def test_ac7_cases_import_rule_unchanged() -> None:
    # the four names of 9b plus the two 9c added; 9d adds none
    names_9b = {"load_case", "record_disposition", "CaseError", "DISPOSITIONS"}
    names_9c = {"summarize", "NarrativeError"}
    assert names_9b | names_9c == ALLOWED_CASES_NAMES


@pytest.mark.parametrize(
    "needle", ["memo_overrides", "memo_classifications", "MEMO_RELABELLED", "insert_df"]
)
def test_ac7_api_has_no_memo_sql_or_audit_names(needle: str) -> None:
    assert [p.name for p in _api_files() if needle in _text(p)] == []


@pytest.mark.parametrize(
    "needle", ["audit(", "relabel_memo", "list_labels", "normalize_memo", "memo_key("]
)
def test_ac7_routers_stay_thin(needle: str) -> None:
    files = sorted((API_SRC / "routers").rglob("*.py"))
    assert files
    assert [f.name for f in files if needle in _text(f)] == []


def test_ac7_memo_package_is_untouched_and_api_free() -> None:
    proc = subprocess.run(
        ["git", "diff", "--stat", BASE_COMMIT, "--", "src/aml/memo"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
    for path in sorted((ROOT / "src" / "aml" / "memo").rglob("*.py")):
        text = _text(path)
        assert "aml.api" not in text, path.name
        assert "fastapi" not in text, path.name


def test_ac7_memo_ddl_unchanged() -> None:
    proc = subprocess.run(
        [
            "git",
            "diff",
            "--stat",
            BASE_COMMIT,
            "--",
            "sql/duckdb/ddl/190_memo_analysis.sql",
            "sql/oracle/ddl/190_memo_analysis.sql",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_ac7_web_sources() -> None:
    types = _text(WEB / "src" / "api" / "caseTypes.ts")
    for name in ("memo_key", "memo_category", "memo_method"):
        assert name in types
    enums = _text(WEB / "src" / "i18n" / "enums.ts")
    for name in ("MEMO_CATEGORY_LABELS", "MEMO_METHOD_LABELS", "forbidden"):
        assert name in enums
    form = WEB / "src" / "pages" / "case" / "MemoRelabelForm.tsx"
    assert form.exists()
    assert "/relabel" in _text(form)


def test_ac7_web_has_no_fetch_or_raw_html() -> None:
    src = WEB / "src"
    sources = sorted([*src.rglob("*.ts"), *src.rglob("*.tsx")])
    assert sources
    assert [p.name for p in (src / "pages").rglob("*.ts*") if "fetch(" in _text(p)] == []
    for needle in ("dangerouslySetInnerHTML", "innerHTML"):
        assert [p.name for p in sources if needle in _text(p)] == []


def test_ac7_mock_config_has_only_sample() -> None:
    assert set(MockConfig.model_fields) == {"sample"}


def test_ac7_prior_tests_stay_green(tmp_path: Path) -> None:
    # own basetemp: the default one is the outer run's, and pytest wipes it at start
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp={tmp_path / 'inner'}",
            "tests/api/test_live_ac2_transactions.py",
            "tests/api/test_live_ac10_cross_cutting.py",
            "tests/memo/test_memo_relabel.py",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:]
