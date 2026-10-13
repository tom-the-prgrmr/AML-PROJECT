"""Run the benchmark: time every (account, T, hops, method) cell on the database as it is now.

Nothing here loads, syncs or generates data. Each cell is ``warmup_runs`` untimed calls followed
by ``runs`` timed calls of ``trace(..., record_audit=False)``; the time kept is
``TraceResult.seconds``. A method that cannot run becomes a ``skipped`` cell and a method that
fails an ``error`` cell, and the run goes on. One ``BENCHMARKED`` audit row is written at the end.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime
from importlib import metadata
from typing import Any

from aml.common.audit import audit
from aml.common.config import PROJECT_ROOT, Settings
from aml.common.db import Database, split_oracle_script
from aml.graph.bench.model import (
    SCHEMA,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_SKIPPED,
    BenchCell,
    BenchError,
    BenchResult,
)
from aml.graph.bench.stats import median, percentile
from aml.graph.model import TraceResult, TraceUnavailableError
from aml.graph.neo4j.sync import source_stats
from aml.graph.trace import METHODS, trace

PROFILE_LABEL = re.compile(r"[A-Za-z0-9._-]+")

PICK_FILE = "bench/pick_accounts.sql"
SYNC_FILE = "bench/sync_costs.sql"
UNKNOWN_PROFILE = "unknown"
AUDIT_MODULE = "graph"


def _statement(db: Database, name: str) -> str:
    """The single statement of a `.sql` file, without the Oracle `/` or a trailing `;`."""
    text = db.sql_file(name).read_text(encoding="utf-8")
    if db.backend == "oracle":
        return split_oracle_script(text)[0]
    return text.strip().rstrip(";")


def pick_accounts(db: Database, settings: Settings) -> list[str]:
    """``bench.accounts`` as given, else the internal accounts with most time-ordered 2-hop paths.

    The count is taken in the largest window of ``bench.hours``; ties go to the smaller id.
    """
    cfg = settings.bench
    if cfg.accounts:
        return list(cfg.accounts)
    binds = {"hours": max(cfg.hours), "top_n": cfg.top_accounts}
    frame = db.query_df(_statement(db, PICK_FILE), binds)
    if frame.empty:
        raise BenchError("no account to benchmark: run aml load first")
    return [str(a) for a in frame["account_id"]]


# ---------------------------------------------------------------------------------- one cell
def _empty_cell(method: str, account: str, hours: int, hops: int) -> BenchCell:
    """An ok cell with every number empty; the caller fills it in or marks it not ok."""
    return BenchCell(
        method=method,
        account=account,
        hours=hours,
        hops=hops,
        status=STATUS_OK,
        reason=None,
        exact=METHODS[method].exact,
        seconds=(),
        median_ms=None,
        p95_ms=None,
        min_ms=None,
        max_ms=None,
        n_paths=None,
        n_accounts=None,
        n_cycles=None,
        query_lines=None,
    )


def _not_ok(base: BenchCell, status: str, reason: str) -> BenchCell:
    return replace(base, status=status, reason=reason)


def _ok_cell(base: BenchCell, timed: list[TraceResult]) -> BenchCell:
    seconds = tuple(r.seconds for r in timed)
    last = timed[-1]
    return replace(
        base,
        seconds=seconds,
        median_ms=median(seconds) * 1000,
        p95_ms=percentile(seconds, 95) * 1000,
        min_ms=min(seconds) * 1000,
        max_ms=max(seconds) * 1000,
        n_paths=last.n_paths,
        n_accounts=last.n_accounts,
        n_cycles=last.n_cycles,
        query_lines=last.query_lines,
    )


class _Runner:
    """Measures cells one after the other; remembers methods that turned out to be unavailable."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.unavailable: dict[str, str] = {}  # method -> reason, found by `prepare` or `run`

    def cell(self, method: str, account: str, hours: int, hops: int) -> BenchCell:
        base = _empty_cell(method, account, hours, hops)
        if self.db.backend not in METHODS[method].backends:
            return _not_ok(base, STATUS_SKIPPED, f"not available on {self.db.backend}")
        if method in self.unavailable:  # `prepare` is tried once per method, not once per cell
            return _not_ok(base, STATUS_SKIPPED, self.unavailable[method])
        cfg = self.settings.bench
        timed: list[TraceResult] = []
        try:
            for run in range(cfg.warmup_runs + cfg.runs):
                result = trace(
                    self.db,
                    self.settings,
                    account,
                    method=method,
                    hops=hops,
                    hours=hours,
                    record_audit=False,
                )
                if run >= cfg.warmup_runs:
                    timed.append(result)
        except TraceUnavailableError as exc:
            self.unavailable[method] = str(exc)
            return _not_ok(base, STATUS_SKIPPED, str(exc))
        except Exception as exc:  # any failure of one cell must not stop the others
            return _not_ok(base, STATUS_ERROR, f"{type(exc).__name__}: {exc}")
        return _ok_cell(base, timed)


# ---------------------------------------------------------------------------------- meta
def _profile(db: Database) -> str:
    """The label of the newest `datagen` / `LOADED` audit row (`small-seed42` -> `small`)."""
    frame = db.query_df(
        "SELECT entity_id FROM audit_log "
        "WHERE module = 'datagen' AND decision = 'LOADED' ORDER BY audit_id DESC"
    )
    if frame.empty:
        return UNKNOWN_PROFILE
    return str(frame["entity_id"].iloc[0]).rsplit("-seed", 1)[0]


def _count(db: Database, table: str) -> int:
    return int(db.query_df(f"SELECT COUNT(*) AS n FROM {table}")["n"].iloc[0])


def _dataset(db: Database) -> dict[str, int]:
    return {
        "customers": _count(db, "customers"),
        "accounts": _count(db, "accounts"),
        "transactions": _count(db, "transactions"),
        "transfers": source_stats(db).transfers,
    }


def _version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _server_version(db: Database) -> str | None:
    sql = {
        "duckdb": "SELECT version() AS v",
        "oracle": "SELECT version_full AS v FROM product_component_version FETCH FIRST 1 ROWS ONLY",
    }[db.backend]
    try:
        return str(db.query_df(sql)["v"].iloc[0])
    except Exception:  # the version is provenance only; a missing grant must not stop the run
        return None


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def _git_commit() -> str | None:
    """Short commit id, with ``-dirty`` when tracked files differ from it (not reproducible)."""
    commit = _git("rev-parse", "--short", "HEAD")
    if not commit:
        return None
    changed = _git("status", "--porcelain", "--untracked-files=no")
    return f"{commit}-dirty" if changed else commit


def _sync_costs(db: Database) -> dict[str, Any] | None:
    """Seconds of the newest FULL and INCREMENTAL sync and the lag the newest run left."""
    try:
        frame = db.query_df(_statement(db, SYNC_FILE))
    except Exception:  # no run log in this database: nothing to report
        return None
    if frame.empty:
        return None

    def newest(mode: str) -> float | None:
        rows = frame[frame["sync_mode"] == mode]
        return None if rows.empty else float(rows["seconds"].iloc[0])

    return {
        "full_seconds": newest("FULL"),
        "incremental_seconds": newest("INCREMENTAL"),
        "lag_after_seconds": int(frame["lag_after_seconds"].iloc[0]),
    }


def _meta(
    db: Database,
    settings: Settings,
    *,
    profile: str,
    command: str,
    started: datetime,
    accounts: list[str],
    sync: dict[str, Any] | None,
) -> dict[str, Any]:
    cfg, limits = settings.bench, settings.trace
    driver = "oracledb" if db.backend == "oracle" else "duckdb"
    return {
        "schema": SCHEMA,
        "profile": profile,
        "backend": db.backend,
        "command": command,
        "started_at": started.isoformat(timespec="seconds"),
        "total_seconds": 0.0,  # set by run_bench once the cells are done
        "git_commit": _git_commit(),
        "versions": {
            "python": platform.python_version(),
            "aml": _version("aml-toolkit"),
            "driver": f"{driver} {_version(driver)}",
            "server": _server_version(db),
            "neo4j_driver": _version("neo4j"),
        },
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "dataset": _dataset(db),
        "params": {
            "hops": list(cfg.hops),
            "hours": list(cfg.hours),
            "runs": cfg.runs,
            "warmup_runs": cfg.warmup_runs,
            "accounts": accounts,
            "picked": not cfg.accounts,
        },
        "trace": {
            "max_paths": limits.max_paths,
            "edge_min_amount_vnd": limits.edge_min_amount_vnd,
            "edge_top_k": limits.edge_top_k,
        },
        "read_timeout_seconds": settings.neo4j.read_timeout_seconds,
        "sync": sync,
    }


# ---------------------------------------------------------------------------------- the run
def run_bench(
    db: Database,
    settings: Settings,
    *,
    profile: str | None = None,
    command: str = "aml bench",
    actor: str | None = None,
) -> BenchResult:
    """Time every cell on ``db`` as it is; write one `BENCHMARKED` audit row; return the result."""
    label = profile or _profile(db)
    if not PROFILE_LABEL.fullmatch(label):  # it becomes part of a file name: fail before timing
        raise BenchError(f"profile label {label!r} must be letters, digits, '.', '_' or '-'")
    accounts = pick_accounts(db, settings)
    started = datetime.now(UTC)
    clock = time.perf_counter()
    cfg = settings.bench
    runner = _Runner(db, settings)
    cells = [
        runner.cell(method, account, hours, hops)
        for account in accounts
        for hours in cfg.hours
        for hops in cfg.hops
        for method in list(METHODS)
    ]
    total = time.perf_counter() - clock
    neo4j_ran = any(c.method == "neo4j" and c.status == STATUS_OK for c in cells)
    meta = _meta(
        db,
        settings,
        profile=label,
        command=command,
        started=started,
        accounts=accounts,
        sync=_sync_costs(db) if neo4j_ran else None,
    )
    meta["total_seconds"] = round(total, 3)
    counts = {
        s: sum(c.status == s for c in cells) for s in (STATUS_OK, STATUS_SKIPPED, STATUS_ERROR)
    }
    audit(
        db,
        module=AUDIT_MODULE,
        entity_type="benchmark",
        entity_id=f"{label}-{db.backend}",
        decision="BENCHMARKED",
        reason=(
            f"trace benchmark on {db.backend} ({label}): {counts[STATUS_OK]} cells ok, "
            f"{counts[STATUS_SKIPPED]} skipped, {counts[STATUS_ERROR]} failed; "
            f"{cfg.runs} timed runs per cell"
        ),
        version=SCHEMA,
        actor=actor or settings.audit.system_actor,
        details={
            "accounts": accounts,
            "hops": list(cfg.hops),
            "hours": list(cfg.hours),
            "runs": cfg.runs,
            "warmup_runs": cfg.warmup_runs,
            "ok": counts[STATUS_OK],
            "skipped": counts[STATUS_SKIPPED],
            "error": counts[STATUS_ERROR],
        },
    )
    return BenchResult(meta=meta, cells=cells)
