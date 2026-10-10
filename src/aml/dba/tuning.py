"""Tuning one slow query with before/after evidence: plan, buffer gets and timing (Oracle only).

The query is the 30-day outflow aggregate per account that Phase 5 monitoring will use. The only
change between the steps is a rewrite of the time predicate (no index, schema or stats change), so
the demo can be re-run any number of times without leaving state behind.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from datetime import timedelta

from aml.common.config import Settings
from aml.common.db import Database
from aml.dba.plans import _month_start

TAG = "aml-tune-demo"
HINT = "/*+ GATHER_PLAN_STATISTICS */"
WINDOW_DAYS = 30


@dataclass(frozen=True)
class TuningStep:
    name: str  # "before" | "after"
    sql: str  # literal predicates, no binds, no hint
    change: str  # one sentence on what changed versus the previous step ("" for before)


@dataclass(frozen=True)
class TuningResult:
    step: TuningStep
    plan: str  # DBMS_XPLAN.DISPLAY_CURSOR(format => 'ALLSTATS LAST')
    plan_hash_value: int
    buffer_gets: int  # Buffers of plan line Id 1 (cumulative) for the last execution
    elapsed_ms: tuple[float, ...]  # one entry per timed run, all rows fetched
    rows: int


def _query(where_time: str, threshold: int) -> str:
    return (
        "SELECT from_account_id, COUNT(*) AS txn_count, SUM(amount_vnd) AS total_out "
        f"FROM transactions WHERE {where_time} AND from_account_id IS NOT NULL "
        f"GROUP BY from_account_id HAVING SUM(amount_vnd) >= {threshold}"
    )


def tuning_steps(settings: Settings) -> list[TuningStep]:
    """Before (function on the partition key) and after (sargable half-open range)."""
    first = _month_start(settings.data.start_date, 2)
    last = first + timedelta(days=WINDOW_DAYS - 1)
    end = first + timedelta(days=WINDOW_DAYS)
    threshold = settings.thresholds.large_cash_vnd
    before = f"TRUNC(txn_ts) BETWEEN DATE '{first.isoformat()}' AND DATE '{last.isoformat()}'"
    after = (
        f"txn_ts >= TIMESTAMP '{first.isoformat()} 00:00:00' "
        f"AND txn_ts < TIMESTAMP '{end.isoformat()} 00:00:00'"
    )
    return [
        TuningStep("before", _query(before, threshold), ""),
        TuningStep(
            "after",
            _query(after, threshold),
            "Rewrote TRUNC(txn_ts) BETWEEN ... as a half-open range on txn_ts so the "
            "optimizer can prune partitions.",
        ),
    ]


def has_cursor_stats_access(db: Database) -> bool:
    """True if the connected user can read the V$ views DISPLAY_CURSOR needs."""
    try:
        for view in ("v$sql", "v$sql_plan_statistics_all"):
            db.query_df(f"SELECT COUNT(*) AS n FROM {view} WHERE 1 = 0")
    except Exception:
        return False
    return True


def _tagged(step: TuningStep) -> str:
    """Executable SQL: hint and tag directly after SELECT so V$SQL can find the cursor."""
    return step.sql.replace("SELECT", f"SELECT {HINT} /* {TAG}:{step.name} */", 1)


def _find_cursor(db: Database, step: TuningStep) -> tuple[str, int, int]:
    """(sql_id, child_number, plan_hash_value) of the latest tagged cursor; never matches itself."""
    prefix = f"SELECT {HINT} /* {TAG}:{step.name} */"
    df = db.query_df(
        "SELECT sql_id, child_number, plan_hash_value FROM v$sql "
        f"WHERE sql_text LIKE '{prefix}%' "
        "AND parsing_schema_name = SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') "
        "ORDER BY last_active_time DESC, child_number DESC FETCH FIRST 1 ROW ONLY"
    )
    if df.empty:
        raise RuntimeError(f"cursor for tuning step {step.name!r} not found in V$SQL")
    row = df.iloc[0]
    return str(row["sql_id"]), int(row["child_number"]), int(row["plan_hash_value"])


def _buffer_gets(db: Database, sql_id: str, child: int) -> int:
    df = db.query_df(
        "SELECT id, last_cr_buffer_gets AS gets FROM v$sql_plan_statistics_all "
        f"WHERE sql_id = '{sql_id}' AND child_number = {child} AND id IN (0, 1) "
        "AND last_cr_buffer_gets IS NOT NULL ORDER BY id DESC"
    )
    if df.empty:
        raise RuntimeError(f"no buffer gets recorded for cursor {sql_id}/{child}")
    return int(df.iloc[0]["gets"])


def _run_step(db: Database, step: TuningStep, runs: int) -> TuningResult:
    sql = _tagged(step)
    db.query_df(sql)  # warm-up, not timed
    timings: list[float] = []
    rows = 0
    for _ in range(runs):
        t0 = time.perf_counter()
        rows = len(db.query_df(sql))
        timings.append((time.perf_counter() - t0) * 1000)
    sql_id, child, plan_hash = _find_cursor(db, step)
    plan_df = db.query_df(
        "SELECT plan_table_output FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR("
        f"'{sql_id}', {child}, 'ALLSTATS LAST'))"
    )
    return TuningResult(
        step=step,
        plan="\n".join(str(x) for x in plan_df["plan_table_output"]),
        plan_hash_value=plan_hash,
        buffer_gets=_buffer_gets(db, sql_id, child),
        elapsed_ms=tuple(timings),
        rows=rows,
    )


def run_tuning(db: Database, settings: Settings, runs: int = 5) -> list[TuningResult]:
    """Run each step once to warm up, then ``runs`` timed times; capture the last cursor's plan."""
    if db.backend != "oracle":
        raise NotImplementedError("run_tuning is Oracle only")
    return [_run_step(db, step, runs) for step in tuning_steps(settings)]


def median_ms(result: TuningResult) -> str:
    return f"{statistics.median(result.elapsed_ms):.3f}"


def render_evidence(
    results: list[TuningResult], *, transactions_rows: int, runs: int, oracle_version: str
) -> str:
    """The evidence file; the last line is the summary and shares its strings with the blocks."""
    lines = [
        "# aml tune-demo: 30-day outflow per account, before/after predicate rewrite",
        f"transactions_rows: {transactions_rows}",
        f"runs: {runs}",
        f"oracle_version: {oracle_version}",
        "",
    ]
    for r in results:
        lines += [
            f"== {r.step.name} ==",
            r.step.sql,
            "",
            f"plan_hash_value: {r.plan_hash_value}",
            f"buffer_gets: {r.buffer_gets}",
            "elapsed_ms: " + " ".join(f"{t:.3f}" for t in r.elapsed_ms),
            f"elapsed_ms_median: {median_ms(r)}",
            f"rows: {r.rows}",
            "",
            r.plan,
            "",
        ]
    b, a = results
    lines.append(
        f"summary: buffer_gets {b.buffer_gets} -> {a.buffer_gets}, "
        f"elapsed_ms_median {median_ms(b)} -> {median_ms(a)}"
    )
    return "\n".join(lines) + "\n"
