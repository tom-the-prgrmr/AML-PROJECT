"""AC1-AC5 and AC10 for specs/dba-runbook-tuning.md (no Oracle needed)."""

from __future__ import annotations

import re

import pytest

from aml.common.config import load_settings
from aml.common.db import split_oracle_script

from .helpers import (
    EVIDENCE,
    HEADINGS,
    ROOT,
    SCRIPTS,
    has_paragraph,
    heading_list,
    mod,
    runbook_text,
    script_files,
    script_index_rows,
    sections,
)

MIN_SCRIPTS = [
    "owner/xplan_display_cursor_last.sql",
    "owner/xplan_explain_typical.sql",
    "owner/partition_and_index_status.sql",
    "sys/010_grant_tuning_views.sql",
    "sys/environment_facts.sql",
    "sys/ash_top_sql.sql",
    "sys/awr_snapshots.sql",
    "reference/rman_backup_full.rman",
    "reference/rman_restore_pitr.rman",
    "reference/enable_archivelog.sql",
    "reference/expdp_schema.par",
    "reference/mv_log_fast_refresh.sql",
    "reference/drop_partition_update_global_indexes.sql",
    "reference/statspack_install.sql",
]

KEYWORDS = {
    "1. Environment and limits": [
        "gvenzl/oracle-free",
        "NOARCHIVELOG",
        "control_management_pack_access",
    ],
    "2. Backup and restore": ["RMAN", "expdp", "impdp", "not available"],
    "3. Reading AWR, ASH and Statspack": [
        "AWR",
        "ASH",
        "Statspack",
        "spcreate.sql",
        "Diagnostics Pack",
    ],
    "4. Reading DBMS_XPLAN output": [
        "DISPLAY_CURSOR",
        "ALLSTATS LAST",
        "GATHER_PLAN_STATISTICS",
        "E-Rows",
        "A-Rows",
        "Buffers",
        "Pstart",
    ],
    "5. Materialized view refresh": [
        "MATERIALIZED VIEW LOG",
        "INCLUDING NEW VALUES",
        "DBMS_MVIEW.EXPLAIN_MVIEW",
        "REFRESH COMPLETE",
        "acct_edge_daily",
    ],
    "6. Partition maintenance": ["UPDATE GLOBAL INDEXES", "p_before_2000", "ORA-14758"],
}

STATUS_BY_DIR = {"owner": "verified", "sys": "manual", "reference": "reference"}


def test_ac1_runbook_has_the_eight_headings_in_order() -> None:
    assert heading_list(runbook_text()) == HEADINGS


def test_ac1_each_numbered_section_has_a_paragraph() -> None:
    secs = sections(runbook_text())
    for name in HEADINGS[:7]:
        assert has_paragraph(secs.get(name, [])), f"section {name!r} has no prose paragraph"


@pytest.mark.parametrize("heading", list(KEYWORDS))
def test_ac2_section_keywords(heading: str) -> None:
    body = "\n".join(sections(runbook_text()).get(heading, [])).lower()
    missing = [k for k in KEYWORDS[heading] if k.lower() not in body]
    assert not missing, f"section {heading!r} lacks {missing}"


def test_ac2_backup_section_states_rman_binary_not_available() -> None:
    body = "\n".join(sections(runbook_text()).get("2. Backup and restore", [])).lower()
    assert "rman" in body
    assert "not available" in body


def test_ac3_every_path_in_runbook_exists() -> None:
    text = runbook_text()
    pattern = r"(?:dba/scripts|results/phase2|sql/oracle)/[A-Za-z0-9_./\-]*"
    paths = {m.group(0).rstrip(".,;:") for m in re.finditer(pattern, text)}
    assert paths, "runbook references no repo paths"
    missing = sorted(p for p in paths if not (ROOT / p).exists())
    assert not missing, f"runbook references missing paths: {missing}"


def test_ac3_script_index_matches_script_directories() -> None:
    rows = script_index_rows(runbook_text())
    files = script_files()
    assert files, "no files under dba/scripts"
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        assert path.parent.parent == SCRIPTS and path.parent.name in STATUS_BY_DIR, rel
        matching = [r for r in rows if r and rel in r[0]]
        assert len(matching) == 1, f"{rel} appears in {len(matching)} Script index rows"
        row = matching[0]
        assert len(row) >= 4, f"{rel}: expected columns Script | Runs as | Status | Purpose"
        assert row[2].lower() == STATUS_BY_DIR[path.parent.name], rel
        if path.suffix == ".rman":
            assert row[2].lower() == "reference", rel


def test_ac3_minimum_scripts_present() -> None:
    missing = [p for p in MIN_SCRIPTS if not (SCRIPTS / p).is_file()]
    assert not missing, f"missing scripts: {missing}"


_STMT_START = re.compile(r"^(SPOOL\b|PROMPT\b|EXIT\b|@)", re.IGNORECASE)


def _code_lines(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.split("--", 1)[0].strip()
        if stripped:
            out.append(stripped)
    return out


def test_ac4_sql_scripts_follow_oracle_convention() -> None:
    sql_files = [p for p in script_files() if p.suffix == ".sql"]
    assert sql_files, "no .sql files under dba/scripts"
    for path in sql_files:
        text = path.read_text(encoding="utf-8")
        statements = split_oracle_script(text)
        assert len(statements) >= 1, path.name
        for line in _code_lines(text):
            assert not line.startswith("SET "), f"{path.name}: {line}"
            assert not _STMT_START.match(line), f"{path.name}: {line}"


def test_ac4_sys_scripts_have_saved_output() -> None:
    sys_scripts = sorted((SCRIPTS / "sys").glob("*.sql"))
    assert sys_scripts, "no dba/scripts/sys/*.sql"
    for path in sys_scripts:
        out = ROOT / "results" / "phase2" / "runbook" / f"{path.stem}.txt"
        assert out.is_file() and out.stat().st_size > 0, f"missing/empty {out}"


def test_ac5_tuning_steps_default_config() -> None:
    tuning = mod("aml.dba.tuning")
    settings = load_settings(
        environ={
            "DB_BACKEND": "duckdb",
            "AML__DATA__START_DATE": "2026-01-01",
            "AML__THRESHOLDS__LARGE_CASH_VND": "400000000",
        }
    )
    steps = tuning.tuning_steps(settings)
    assert [s.name for s in steps] == ["before", "after"]
    before, after = steps
    assert "TRUNC(txn_ts) BETWEEN DATE '2026-03-01' AND DATE '2026-03-30'" in before.sql
    assert (
        "txn_ts >= TIMESTAMP '2026-03-01 00:00:00' AND txn_ts < TIMESTAMP '2026-03-31 00:00:00'"
        in after.sql
    )
    assert "TRUNC(" not in after.sql
    for step in steps:
        assert "HAVING SUM(amount_vnd) >= 400000000" in step.sql
        assert "/*+" not in step.sql
    assert before.change == ""
    assert after.change != ""


def test_ac5_tuning_steps_follow_config_overrides() -> None:
    tuning = mod("aml.dba.tuning")
    settings = load_settings(
        environ={
            "DB_BACKEND": "duckdb",
            "AML__DATA__START_DATE": "2026-02-01",
            "AML__THRESHOLDS__LARGE_CASH_VND": "300000000",
        }
    )
    before, after = tuning.tuning_steps(settings)
    assert ">= 300000000" in before.sql
    assert ">= 300000000" in after.sql
    assert "DATE '2026-04-01' AND DATE '2026-04-30'" in before.sql
    assert "txn_ts >= TIMESTAMP '2026-04-01 00:00:00'" in after.sql
    assert "txn_ts < TIMESTAMP '2026-05-01 00:00:00'" in after.sql


def _evidence_block(text: str, name: str) -> str:
    m = re.search(rf"^== {name} ==\s*$(.*?)(?=^== |\Z)", text, re.MULTILINE | re.DOTALL)
    assert m, f"no '== {name} ==' block in {EVIDENCE}"
    return m.group(1)


def _field(block: str, key: str) -> str:
    m = re.search(rf"^{key}: *(\S+)\s*$", block, re.MULTILINE)
    assert m, f"no '{key}:' line"
    return m.group(1)


def test_ac10_runbook_tuning_section_matches_evidence_file() -> None:
    assert EVIDENCE.is_file(), f"missing committed evidence {EVIDENCE}"
    evidence = EVIDENCE.read_text(encoding="utf-8")
    section = "\n".join(sections(runbook_text()).get("7. Tuning walkthrough", []))
    flat = re.sub(r"(?<=\d),(?=\d)", "", section)  # tolerate thousands separators

    assert "uv run aml tune-demo" in section
    assert "results/phase2/tune_demo.txt" in section

    before = _evidence_block(evidence, "before")
    after = _evidence_block(evidence, "after")
    assert _field(before, "plan_hash_value") != _field(after, "plan_hash_value")

    for key in ("plan_hash_value", "buffer_gets", "elapsed_ms_median"):
        for block in (before, after):
            value = _field(block, key)
            assert re.search(rf"(?<![\d.]){re.escape(value)}(?![\d])", flat), (
                f"section 7 lacks {key}={value}"
            )

    rows = re.search(r"^transactions_rows: *(\d+)\s*$", evidence, re.MULTILINE)
    assert rows, "evidence lacks transactions_rows"
    assert re.search(rf"(?<![\d.]){rows.group(1)}(?![\d])", flat), (
        "section 7 lacks transactions_rows"
    )
