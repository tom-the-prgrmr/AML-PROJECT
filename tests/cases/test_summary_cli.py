"""AC5 for specs/case-summary.md: `aml cases summary` on TINY (DuckDB).

TINY after `load`, `er`, `screen`, `monitor`, `network` and `aml cases build` is built once per
module (the `sources` stage plus `run_cases`, which is what `aml cases build` runs) and every test
works on a private copy of that file, so the module costs one build.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import get_settings
from aml.common.db import DuckDb

from .helpers import TINY_CASE, cli, count, duck_settings, query, run_cases
from .summary_helpers import (
    SECTION_PREFIXES,
    WATERMARK,
    block,
    headings,
)

ROOT = Path(__file__).resolve().parents[2]
TINY_NAME = "Đỗ T. H."  # CIF00000189 in customers_masked
TINY_REAL_NAME = "Đỗ Thị Huyền"  # CIF00000189 in customers
FOOTER = "Template summary/v1; case run 1; no LLM was used."


@pytest.fixture(scope="module")
def built(tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> Path:
    """TINY `sources` stage after one `run_cases` (52 cases)."""
    path = tmp_path_factory.mktemp("summary_cli") / "built.duckdb"
    shutil.copy(tiny_stages["sources"], path)
    with DuckDb(path) as db:
        run_cases(db, duck_settings())
    return path


@pytest.fixture
def use_built(
    built: Path,
    tiny_env: Callable[..., dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """The built TINY file, copied where the CLI looks for it."""
    path = tmp_path / "tiny.duckdb"
    shutil.copy(built, path)
    for key, value in tiny_env().items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return path


@pytest.fixture
def injection_memos(use_built: Path) -> Iterator[list[str]]:
    with DuckDb(use_built) as db:
        df = query(
            db,
            "SELECT t.memo FROM ground_truth g JOIN transactions t ON t.txn_id = g.entity_id "
            "WHERE g.typology = 'prompt_injection' AND g.entity_type = 'transaction'",
        )
    memos = [str(m) for m in df["memo"]]
    assert len(memos) == 6
    yield memos


def _text(result: Any) -> str:
    return str(result.stdout_bytes.decode("utf-8"))


def _alert_rows(text: str) -> list[str]:
    bars = [ln for ln in block(text, "## Alerts") if ln.startswith("|")]
    return bars[2:]


def test_ac5_single_case_summary_on_tiny(use_built: Path) -> None:
    result = cli("cases", "summary", TINY_CASE)
    assert result.exit_code == 0, result.output + result.stderr
    text = _text(result)
    lines = text.splitlines()
    assert lines[0] == "# Case C-CIF00000189-20260413"
    for line in (
        "- Alerts: 5 (3 RULE, 2 NETWORK, 0 SCREENING) between 2026-04-13 09:28:12 "
        "and 2026-04-18 10:04:12",
        "- Priority: not scored",
        "## Activity from 2026-01-19 to 2026-04-18",
        "- 34 transaction(s) on 5 day(s): 31 in totalling 2,930,380,000 VND, "
        "3 out totalling 2,851,894,000 VND",
        "- 34 counterparty(ies); largest transaction 1,019,225,000 VND",
        "- Graph features (networkx): in-degree 31, out-degree 3, PageRank ratio 6.77, "
        "shared cluster SHARED-CIF00000002 (29 customers), hub yes, cycle alerts 0",
    ):
        assert line in lines, line
    assert len(_alert_rows(text)) == 5
    assert lines[-1] == FOOTER
    # the masked name is shown, the name of `customers` is not
    with DuckDb(use_built) as db:
        masked = query(db, "SELECT full_name FROM customers_masked WHERE cif = 'CIF00000189'")
        real = query(db, "SELECT full_name FROM customers WHERE cif = 'CIF00000189'")
    assert masked["full_name"].iloc[0] == TINY_NAME
    assert real["full_name"].iloc[0] == TINY_REAL_NAME
    assert TINY_NAME in text
    assert TINY_REAL_NAME not in text


def test_ac5_all_writes_one_file_per_case(use_built: Path, tmp_path: Path) -> None:
    single = _text(cli("cases", "summary", TINY_CASE))
    with DuckDb(use_built) as db:
        case_ids = sorted(query(db, "SELECT case_id FROM cases_current")["case_id"])
        audit_before = count(db, "audit_log")
    assert len(case_ids) == 52

    out = tmp_path / "sum"
    result = cli("cases", "summary", "--all", "--out-dir", str(out))
    assert result.exit_code == 0, result.output + result.stderr
    assert "wrote 52 summaries to" in result.stdout
    files = sorted(p.name for p in out.iterdir())
    assert files == [f"{c}.md" for c in case_ids]
    assert (out / f"{TINY_CASE}.md").read_text(encoding="utf-8") == single

    for path in out.iterdir():
        text = path.read_text(encoding="utf-8")
        found = headings(text)
        assert len(found) == 7, path.name
        assert all(h.startswith(p) for h, p in zip(found, SECTION_PREFIXES, strict=True)), path.name
        assert WATERMARK in text, path.name

    again = tmp_path / "sum_again"
    assert cli("cases", "summary", "--all", "--out-dir", str(again)).exit_code == 0
    for name in files:
        assert (out / name).read_bytes() == (again / name).read_bytes(), name

    one = tmp_path / "one.md"
    result = cli("cases", "summary", TINY_CASE, "--out", str(one))
    assert result.exit_code == 0, result.output + result.stderr
    assert "wrote" in result.stdout
    assert one.read_text(encoding="utf-8") == single

    with DuckDb(use_built) as db:
        assert count(db, "audit_log") == audit_before  # reading a summary writes no audit row


def test_ac5_no_summary_carries_a_prompt_injection_memo(
    use_built: Path, injection_memos: list[str], tmp_path: Path
) -> None:
    out = tmp_path / "sum"
    assert cli("cases", "summary", "--all", "--out-dir", str(out)).exit_code == 0
    tails = [m.rsplit(". ", 1)[-1].lower() for m in injection_memos]
    for path in out.iterdir():
        text = path.read_text(encoding="utf-8").lower()
        assert "ignore previous instructions" not in text, path.name
        for memo, tail in zip(injection_memos, tails, strict=True):
            assert memo.lower() not in text, path.name
            assert tail not in text, path.name


def test_ac5_bad_arguments_and_unknown_case(use_built: Path, tmp_path: Path) -> None:
    unknown = cli("cases", "summary", "C-NOPE-20260101")
    assert unknown.exit_code == 1, unknown.output
    assert "unknown case_id" in unknown.stderr
    assert cli("cases", "summary", "--all").exit_code == 2  # no --out-dir
    assert cli("cases", "summary").exit_code == 2  # nothing to summarise
    both = cli("cases", "summary", TINY_CASE, "--all", "--out-dir", str(tmp_path / "x"))
    assert both.exit_code == 2, both.output
    assert not (tmp_path / "x").exists() or not list((tmp_path / "x").iterdir())


def test_ac5_stdout_is_utf8_whatever_the_console_code_page(
    use_built: Path, tiny_env: Callable[..., dict[str, str]]
) -> None:
    """A real process with a piped stdout: on Windows its default code page cannot print `Đ`."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env.update(tiny_env())
    code = "from aml.cli import app; app()"
    proc = subprocess.run(
        [sys.executable, "-c", code, "cases", "summary", TINY_CASE],
        capture_output=True,
        env=env,
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    text = proc.stdout.decode("utf-8")
    assert text.splitlines()[0] == "# Case C-CIF00000189-20260413"
    assert TINY_NAME in text
    assert text.splitlines()[-1] == FOOTER
