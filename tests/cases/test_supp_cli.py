"""AC8 for specs/case-suppression.md: `aml cases build` (extra lines) and `aml cases suppressed`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .helpers import cli, has
from .supp_helpers import GG_CASE, GG_KEY

UseStage = Callable[[str], Path]


def _dispose() -> None:
    result = cli(
        "cases",
        "dispose",
        GG_CASE,
        "--disposition",
        "FALSE_POSITIVE",
        "--reason",
        "namesake",
        "--actor",
        "analyst01",
    )
    assert result.exit_code == 0, result.output


def test_ac8_build_prints_the_rule_lines(cli_db: UseStage) -> None:
    cli_db("sources")
    first = cli("cases", "build")
    assert first.exit_code == 0, first.output
    lines = first.stdout.splitlines()
    assert any(has(ln, "GOOD_GUY suppressed=0") for ln in lines)
    assert any(has(ln, "HIBERNATION suppressed=0") for ln in lines)


def test_ac8_suppressed_before_any_disposition_lists_nothing(cli_db: UseStage) -> None:
    cli_db("sources")
    assert cli("cases", "build").exit_code == 0
    result = cli("cases", "suppressed")
    assert result.exit_code == 0, result.output
    assert "0 suppressed item(s)" in result.stdout


def test_ac8_dispose_build_suppressed(cli_db: UseStage) -> None:
    cli_db("sources")
    assert cli("cases", "build").exit_code == 0
    _dispose()
    built = cli("cases", "build")
    assert built.exit_code == 0, built.output
    lines = built.stdout.splitlines()
    summary = [ln for ln in lines if "run_id=2" in ln]
    assert len(summary) == 1
    for token in ("run_id=2", "items=74", "suppressed=1", "active=73", "cases=51"):
        assert has(summary[0], token), token
    assert any(has(ln, "GOOD_GUY suppressed=1") for ln in lines)
    assert any(has(ln, "HIBERNATION suppressed=0") for ln in lines)

    listed = cli("cases", "suppressed")
    assert listed.exit_code == 0, listed.output
    rows = [ln for ln in listed.stdout.splitlines() if GG_KEY in ln]
    assert len(rows) == 1
    assert "GOOD_GUY" in rows[0]
    assert "valid until 2027-06-30" in rows[0]


def test_ac8_suppressed_limit_option(cli_db: UseStage) -> None:
    cli_db("sources")
    assert cli("cases", "build").exit_code == 0
    _dispose()
    assert cli("cases", "build").exit_code == 0
    result = cli("cases", "suppressed", "--limit", "1")
    assert result.exit_code == 0, result.output
    assert GG_KEY in result.stdout


def test_ac8_suppressed_before_any_build_exits_1(cli_db: UseStage) -> None:
    cli_db("sources")
    result = cli("cases", "suppressed")
    assert result.exit_code == 1, result.output
    assert "run `aml cases build` first" in result.stderr
