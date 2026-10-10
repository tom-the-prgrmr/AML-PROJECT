"""Helpers for the Phase 2d tests: runbook parsing and repo paths."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "dba" / "RUNBOOK.md"
SCRIPTS = ROOT / "dba" / "scripts"
EVIDENCE = ROOT / "results" / "phase2" / "tune_demo.txt"

HEADINGS = [
    "1. Environment and limits",
    "2. Backup and restore",
    "3. Reading AWR, ASH and Statspack",
    "4. Reading DBMS_XPLAN output",
    "5. Materialized view refresh",
    "6. Partition maintenance",
    "7. Tuning walkthrough",
    "Script index",
]

GRANT_SCRIPT = "dba/scripts/sys/010_grant_tuning_views.sql"


def mod(name: str) -> Any:
    return importlib.import_module(name)


def runbook_text() -> str:
    assert RUNBOOK.is_file(), f"missing {RUNBOOK}"
    return RUNBOOK.read_text(encoding="utf-8")


def sections(text: str) -> dict[str, list[str]]:
    """Level-2 heading (without ``## ``) -> body lines; headings inside code fences are ignored."""
    out: dict[str, list[str]] = {}
    current: list[str] | None = None
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            current = out.setdefault(line[3:].strip(), [])
            continue
        if current is not None:
            current.append(line)
    return out


def heading_list(text: str) -> list[str]:
    result: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            result.append(line[3:].strip())
    return result


def has_paragraph(lines: list[str]) -> bool:
    """True if the body has a non-empty line that is prose (not a heading, table or code)."""
    in_fence = False
    for line in lines:
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s or s.startswith(("#", "|", "<!--")):
            continue
        return True
    return False


def script_index_rows(text: str) -> list[list[str]]:
    """Data rows of the table under ``## Script index`` as stripped cells (backticks removed)."""
    rows: list[list[str]] = []
    for line in sections(text).get("Script index", []):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip().strip("`").strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        if cells and cells[0].lower() == "script":
            continue
        rows.append(cells)
    return rows


def script_files() -> list[Path]:
    return sorted(p for p in SCRIPTS.rglob("*") if p.is_file())
