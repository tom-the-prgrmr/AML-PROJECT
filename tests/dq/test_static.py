"""AC1-AC2 for specs/dq-framework.md: catalogue, SQL files, DDL and rule synchronisation."""

from __future__ import annotations

import re
from datetime import date

from aml.common.config import Settings
from aml.common.db import SQL_ROOT, DuckDb, split_oracle_script, sql_file

from .helpers import ALL_RULES, by_rule, mod

DIMS = {"COMPLETENESS", "VALIDITY", "UNIQUENESS", "CONSISTENCY", "TIMELINESS"}


def _strip_comments(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("--")).strip()


def test_ac1_ten_rules_cover_five_dimensions() -> None:
    rules = mod("aml.dq.rules")
    assert [r.rule_id for r in rules.RULES] == list(ALL_RULES)
    assert set(rules.DIMENSIONS) == DIMS
    assert {r.dimension for r in rules.RULES} == DIMS
    cust = {r.dimension for r in rules.RULES if r.table_name == "customers"}
    txn = {r.dimension for r in rules.RULES if r.table_name == "transactions"}
    assert cust == {"COMPLETENESS", "VALIDITY", "CONSISTENCY"}
    assert txn == {"UNIQUENESS", "VALIDITY", "CONSISTENCY", "TIMELINESS"}


def test_ac1_check_sql_resolves_for_both_backends_with_one_select() -> None:
    for rule in mod("aml.dq.rules").RULES:
        for backend in ("duckdb", "oracle"):
            path = sql_file(rule.check_sql, backend)
            assert path.is_file(), (rule.rule_id, backend)
            text = path.read_text(encoding="utf-8")
            if SQL_ROOT / "oracle" in path.parents:
                statements = split_oracle_script(text)
            else:
                statements = [s for s in _strip_comments(text).split(";") if s.strip()]
            assert len(statements) == 1, (rule.rule_id, backend)
            body = _strip_comments(statements[0])
            assert re.match(r"(?is)(SELECT|WITH)\b", body), (rule.rule_id, backend)


def test_ac1_dq_ddl_in_schema_scripts_for_both_backends() -> None:
    scripts = mod("aml.dba.schema").SCHEMA_SCRIPTS
    for backend in ("duckdb", "oracle"):
        assert "ddl/060_dq.sql" in scripts[backend]
        resolved = sql_file("ddl/060_dq.sql", backend)
        assert resolved.is_file()
        assert resolved.parent.parent == SQL_ROOT / backend


def test_ac2_schema_and_sync_rules_idempotent_and_operator_edits_kept(
    duck: DuckDb, dq_settings: Settings
) -> None:
    schema = mod("aml.dba.schema")
    rules = mod("aml.dq.rules")
    schema.apply_schema(duck)
    schema.apply_schema(duck)
    assert rules.sync_rules(duck) == 10
    assert rules.sync_rules(duck) == 0
    assert int(duck.query_df("SELECT COUNT(*) FROM dq_rules").iloc[0, 0]) == 10
    assert int(duck.query_df("SELECT COUNT(*) FROM dq_results").iloc[0, 0]) == 0
    assert int(duck.query_df("SELECT COUNT(*) FROM dq_trend").iloc[0, 0]) == 0

    duck.execute("UPDATE dq_rules SET enabled = FALSE WHERE rule_id = 'TXN_FEED_STALE'")
    assert rules.sync_rules(duck) == 0
    enabled = duck.query_df("SELECT enabled FROM dq_rules WHERE rule_id = 'TXN_FEED_STALE'")
    assert bool(enabled.iloc[0, 0]) is False

    run = mod("aml.dq.runner").run_dq(duck, dq_settings, as_of=date(2026, 6, 30))
    assert len(run.results) == 9
    assert "TXN_FEED_STALE" not in by_rule(run)
