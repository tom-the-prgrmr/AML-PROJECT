"""Single command-line entry point: ``uv run aml <command>``.

The Makefile and ``tasks.ps1`` are thin wrappers around these commands so the project
runs the same way on Linux/macOS and on Windows without ``make``.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from aml.assistant import rag_cli
from aml.assistant.eval import cli as eval_cli
from aml.assistant.eval.model import EvalError, GoldenError
from aml.assistant.evidence import RetrievalError, RetrievalUnavailableError
from aml.assistant.knowledge.model import KnowledgeError
from aml.assistant.llm import LLMError, OllamaUnavailableError
from aml.cases.chain import ACTOR, NOTE, label_line, run_chain, train_line
from aml.cases.dispositions import DISPOSITIONS, record_disposition
from aml.cases.labels import simulate_dispositions
from aml.cases.model import PrioritizationError
from aml.cases.narrative import NarrativeError, as_file_bytes, summarize, write_summaries
from aml.cases.prioritize import KINDS, train
from aml.cases.runner import CaseError, run_cases
from aml.cases.view import list_suppressed, load_case
from aml.common.audit import audit
from aml.common.config import Settings, get_settings
from aml.common.db import Database, ServiceUnavailableError, get_db
from aml.common.services import all_statuses
from aml.datagen.load import LoadError, load_parquet, read_manifest
from aml.datagen.pipeline import run_pipeline
from aml.dba.plans import explain_plan, pruning_queries
from aml.dba.retention import RetentionError, purge_transactions
from aml.dba.schema import apply_schema
from aml.dba.security import SecurityConfigError, apply_security
from aml.dba.tuning import has_cursor_stats_access, median_ms, render_evidence, run_tuning
from aml.dq.runner import label_agreement, run_dq
from aml.entity_resolution.evaluate import evaluate_er
from aml.entity_resolution.runner import ErError, explain_cluster, run_er
from aml.graph.bench.model import STATUS_OK, BenchError
from aml.graph.bench.report import path_mismatches, write_report, write_result
from aml.graph.bench.runner import run_bench
from aml.graph.model import TraceUnavailableError
from aml.graph.neo4j import client
from aml.graph.neo4j.client import open_driver
from aml.graph.neo4j.extract import NODE_LABELS, REL_TYPES, SyncError
from aml.graph.neo4j.gds import run_gds
from aml.graph.neo4j.guard import GraphError
from aml.graph.neo4j.queries import QUERY_NAMES, QueryError
from aml.graph.neo4j.queries import run_query as run_graph_query
from aml.graph.neo4j.sync import graph_counts, read_state, run_sync, source_stats
from aml.graph.network.evaluate import evaluate_network, network_coverage
from aml.graph.network.runner import NetworkError, run_network
from aml.graph.trace import METHODS, TraceError, TraceResult
from aml.graph.trace import trace as run_trace
from aml.memo.cli import memo_app
from aml.monitoring.evaluate import evaluate_rules, typology_coverage
from aml.monitoring.runner import MonitoringError, run_monitoring
from aml.screening.evaluate import evaluate, truth_pairs
from aml.screening.incremental import run_incremental
from aml.screening.runner import ScreeningError, run_screening
from aml.screening.sql_compare import compare_sql_python

app = typer.Typer(add_completion=False, help="AML Investigation Toolkit")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@app.command()
def status() -> None:
    """Show active config and which optional services are reachable."""
    s = get_settings()
    typer.echo(f"DB_BACKEND={s.db.backend}  profile={s.data.profile}  seed={s.seed}")
    for st in all_statuses(s):
        mark = "UP  " if st.up else "DOWN"
        typer.echo(f"  [{mark}] {st.name:<7} {st.detail}")


@app.command("init-db")
def init_db() -> None:
    """Create the base schema (audit_log) on the configured backend."""
    with get_db() as db:
        n = sum(apply_schema(db).values())
        audit(
            db,
            module="setup",
            entity_type="schema",
            entity_id="audit_log",
            decision="CREATED",
            reason=f"init-db ran {n} statement(s) on {db.backend}",
            version="ddl/000",
        )
        count = db.query_df("SELECT COUNT(*) AS n FROM audit_log")["n"].iloc[0]
        typer.echo(f"backend={db.backend}: audit_log ready, {count} row(s)")


@app.command("explain-pruning")
def explain_pruning(
    out: Annotated[Path, typer.Option(help="Where to write the plans.")] = Path(
        "results/phase2/partition_pruning.txt"
    ),
) -> None:
    """Capture partition-pruning execution plans for `transactions` (Oracle only)."""
    s = get_settings()
    with get_db(s) as db:
        if db.backend != "oracle":
            typer.echo("explain-pruning: Oracle only (active backend is duckdb).", err=True)
            raise typer.Exit(code=2)
        blocks = [
            f"== {q.name} (expected {q.expected_op}) ==\n{q.sql}\n\n{explain_plan(db, q.sql)}\n"
            for q in pruning_queries(s)
        ]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(blocks), encoding="utf-8")
        audit(
            db,
            module="dba",
            entity_type="table",
            entity_id="transactions",
            decision="EVIDENCE_CAPTURED",
            reason=(
                f"Captured {len(blocks)} partition-pruning execution plans "
                "(single, iterator, all) for transactions."
            ),
            details={"path": str(out)},
        )
    typer.echo(f"wrote {len(blocks)} plans to {out}")


@app.command("tune-demo")
def tune_demo(
    out: Annotated[Path, typer.Option(help="Where to write the evidence.")] = Path(
        "results/phase2/tune_demo.txt"
    ),
    runs: Annotated[int, typer.Option(min=1, help="Timed runs per step.")] = 5,
) -> None:
    """Tune the 30-day outflow query and capture before/after plans and timings (Oracle only)."""
    s = get_settings()
    with get_db(s) as db:
        if db.backend != "oracle":
            typer.echo(f"tune-demo: Oracle only (active backend is {db.backend}).", err=True)
            raise typer.Exit(code=2)
        if not has_cursor_stats_access(db):
            typer.echo(
                "tune-demo: no access to V$ views; apply "
                "dba/scripts/sys/010_grant_tuning_views.sql as SYS (see dba/RUNBOOK.md).",
                err=True,
            )
            raise typer.Exit(code=1)
        n_rows = int(db.query_df("SELECT COUNT(*) AS n FROM transactions").iloc[0, 0])
        banner = str(db.query_df("SELECT banner FROM v$version").iloc[0, 0])
        before, after = results = run_tuning(db, s, runs=runs)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            render_evidence(results, transactions_rows=n_rows, runs=runs, oracle_version=banner),
            encoding="utf-8",
        )
        audit(
            db,
            module="dba",
            entity_type="query",
            entity_id="outflow_30d",
            decision="TUNING_CAPTURED",
            reason=(
                f"{after.step.change} Buffer gets {before.buffer_gets} -> {after.buffer_gets}, "
                f"median {median_ms(before)} -> {median_ms(after)} ms over {runs} runs."
            ),
            details={
                "path": str(out),
                "before": {"plan_hash_value": before.plan_hash_value},
                "after": {"plan_hash_value": after.plan_hash_value},
            },
        )
    typer.echo(f"wrote tuning evidence to {out}")


@app.command("security-setup")
def security_setup() -> None:
    """Create Oracle roles, demo users, grants and audit policies (Oracle only, idempotent)."""
    try:
        result = apply_security(get_settings())
    except (NotImplementedError, SecurityConfigError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    for key, names in result.items():
        typer.echo(f"{key}: {', '.join(names)}")


@app.command()
def retention(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: data.reference_date)."),
    ] = None,
    execute: Annotated[
        bool, typer.Option("--execute", help="Archive and drop (default: dry run).")
    ] = False,
) -> None:
    """Archive then drop `transactions` partitions older than the retention cutoff (Oracle only)."""
    s = get_settings()
    with get_db(s) as db:
        try:
            plan = purge_transactions(
                db, s, as_of=as_of.date() if as_of else None, dry_run=not execute
            )
        except RetentionError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
    label = "EXECUTED" if plan.executed else "DRY RUN"
    typer.echo(
        f"{label}: {plan.table} as_of={plan.as_of} cutoff={plan.cutoff.date()} "
        f"retention_months={plan.retention_months}: {len(plan.drop)} partition(s)"
    )
    for a in plan.drop:
        typer.echo(
            f"  {a.month} partition={a.partition} rows={a.rows} archive_path={a.archive_path}"
        )


PROFILES = ("small", "dense", "large")


@app.command()
def data(
    profile: Annotated[
        str | None, typer.Option(help="Size profile: small, dense or large.")
    ] = None,
    seed: Annotated[int | None, typer.Option(help="Random seed.")] = None,
    out: Annotated[Path | None, typer.Option(help="Output directory for Parquet files.")] = None,
) -> None:
    """Generate the synthetic dataset as Parquet files (CLI > env > config.yaml)."""
    s = get_settings()
    chosen = profile if profile is not None else s.data.profile
    if chosen not in PROFILES:
        typer.echo(f"Unknown profile '{chosen}'. Valid profiles: {', '.join(PROFILES)}.", err=True)
        raise typer.Exit(code=2)
    s = s.model_copy(
        update={
            "seed": s.seed if seed is None else seed,
            "data": s.data.model_copy(update={"profile": chosen}),
        }
    )
    target = out if out is not None else Path(s.data.output_dir)
    manifest = run_pipeline(s, target)
    total = sum(manifest.tables.values())
    typer.echo(
        f"profile={manifest.profile} seed={manifest.seed}: wrote {len(manifest.tables)} tables "
        f"({total} rows) to {target}"
    )


@app.command()
def load(
    backend: Annotated[
        str | None, typer.Option(help="Target backend: duckdb or oracle (default: DB_BACKEND).")
    ] = None,
    src: Annotated[Path | None, typer.Option(help="Parquet directory (default: data dir).")] = None,
) -> None:
    """Load the Parquet dataset into the database (idempotent: tables are replaced)."""
    if backend is not None and backend not in ("duckdb", "oracle"):
        typer.echo(f"Unknown backend '{backend}'. Valid backends: duckdb, oracle.", err=True)
        raise typer.Exit(code=2)
    s = get_settings()
    source = src if src is not None else Path(s.data.output_dir)
    try:
        read_manifest(source)
    except LoadError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    with get_db(s, backend) as db:
        counts = load_parquet(db, source)
        typer.echo(
            f"backend={db.backend}: loaded {len(counts)} tables ({sum(counts.values())} rows)"
        )


dq_app = typer.Typer(add_completion=False, help="Data quality rules and results.")
app.add_typer(dq_app, name="dq")


@dq_app.command("run")
def dq_run(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: data.reference_date)."),
    ] = None,
) -> None:
    """Run every enabled data quality rule; FAIL results are measurements, not errors."""
    s = get_settings()
    with get_db(s) as db:
        run = run_dq(db, s, as_of=as_of.date() if as_of else None)
        for r in run.results:
            rate = "n/a" if r.fail_rate is None else f"{r.fail_rate:.6f}"
            typer.echo(
                f"{r.rule_id:<26} {r.status:<7} failed={r.failed_rows}/{r.total_rows} rate={rate}"
            )
        passed = sum(r.status == "PASS" for r in run.results)
        failed = sum(r.status == "FAIL" for r in run.results)
        typer.echo(
            f"run_id={run.run_id} as_of={run.as_of}: {passed} PASS, {failed} FAIL, "
            f"{len(run.results) - passed - failed} NO_DATA"
        )
        labelled = int(db.query_df("SELECT COUNT(*) AS n FROM dq_labels")["n"].iloc[0])
        if labelled:
            for row in label_agreement(db, run).itertuples():
                typer.echo(
                    f"{row.rule_id:<26} vs {row.defect_type}: "
                    f"precision={row.precision:.2f} recall={row.recall:.2f}"
                )


@app.command()
def screen(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: data.reference_date)."),
    ] = None,
    eval_out: Annotated[
        Path | None, typer.Option(help="Write the evaluation table to this CSV file.")
    ] = None,
    incremental: Annotated[
        bool,
        typer.Option("--incremental", help="Re-screen only what changed since the last FULL run."),
    ] = False,
) -> None:
    """Screen all customers against the watchlist (two tiers) and evaluate against ground truth."""
    s = get_settings()
    run_fn = run_incremental if incremental else run_screening
    with get_db(s) as db:
        try:
            run = run_fn(db, s, as_of=as_of.date() if as_of else None)
        except ScreeningError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(
            f"run_id={run.run_id} mode={run.mode} as_of={run.as_of} "
            f"customers={run.customers_screened} entries={run.entries_screened} "
            f"candidates={run.candidate_pairs} recorded={run.recorded} ALERT={run.alerts} "
            f"REVIEW={run.reviews} AUTO_CLEARED={run.auto_cleared} superseded={run.superseded}"
        )
        if not truth_pairs(db):
            return
        table = evaluate(db, s)
        for r in table.itertuples():
            pct = "n/a" if r.fp_reduction_pct is None else f"{r.fp_reduction_pct:.2f}%"
            typer.echo(
                f"{r.method:<15} flagged={r.flagged} tp={r.tp} fp={r.fp} fn={r.fn} "
                f"precision={r.precision:.2f} recall={r.recall:.2f} fp_reduction={pct}"
            )
        if eval_out is not None:
            eval_out.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(eval_out, index=False, encoding="utf-8")


@app.command("screen-compare")
def screen_compare() -> None:
    """Compare the in-database SQL screen (Jaro-Winkler) with the two-tier Python screen."""
    s = get_settings()
    with get_db(s) as db:
        try:
            c = compare_sql_python(db, s)
        except ScreeningError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(
            f"backend={c.backend} function={c.function} threshold={c.threshold} "
            f"sql_pairs={c.sql_pairs} python_pairs={c.python_pairs} both={c.both} "
            f"sql_only={c.sql_only} python_only={c.python_only} truth={c.truth} "
            f"sql_tp={c.sql_tp} python_tp={c.python_tp} sql_seconds={c.sql_seconds:.3f}"
        )


def _explain(db: Database, golden_customer_id: str) -> None:
    pairs = explain_cluster(db, golden_customer_id)  # raises ErError for an unknown id
    gid = golden_customer_id.replace("'", "''")
    size = int(
        db.query_df(
            f"SELECT COUNT(*) AS n FROM customer_golden WHERE golden_customer_id = '{gid}'"
        )["n"].iloc[0]
    )
    weakest = "n/a" if pairs.empty else f"{pairs['match_weight'].min():.2f}"
    typer.echo(
        f"{golden_customer_id} cluster_size={size} pairs={len(pairs)} min_match_weight={weakest}"
    )
    for r in pairs.itertuples():
        typer.echo(
            f"  {r.cif_l} {r.cif_r} weight={r.match_weight:.2f} prior={r.mw_prior:+.2f} "
            f"name={r.mw_name:+.2f} dob={r.mw_dob:+.2f} phone={r.mw_phone:+.2f} "
            f"email={r.mw_email:+.2f} address={r.mw_address:+.2f} id={r.mw_id:+.2f}"
        )


@app.command()
def er(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: data.reference_date)."),
    ] = None,
    eval_out: Annotated[
        Path | None, typer.Option(help="Write the evaluation table to this CSV file.")
    ] = None,
    explain: Annotated[
        str | None,
        typer.Option(help="Show the match weights of one golden customer (reads, no new run)."),
    ] = None,
) -> None:
    """Resolve customers into golden ids with Splink and evaluate against ground truth."""
    s = get_settings()
    with get_db(s) as db:
        try:
            if explain is not None:
                _explain(db, explain)
                return
            run = run_er(db, s, as_of=as_of.date() if as_of else None)
        except ErError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(
            f"run_id={run.run_id} as_of={run.as_of} customers={run.customers_resolved} "
            f"blocked_pairs={run.blocked_pairs} MATCH={run.match_pairs} "
            f"REVIEW={run.review_pairs} clusters={run.clusters} "
            f"merged_clusters={run.merged_clusters} merged_cifs={run.merged_cifs}"
        )
        if int(db.query_df("SELECT COUNT(*) AS n FROM customer_person")["n"].iloc[0]) == 0:
            return
        table = evaluate_er(db)
        for r in table.itertuples():
            typer.echo(
                f"{r.level:<9} predicted={r.predicted} truth={r.truth} tp={r.tp} fp={r.fp} "
                f"fn={r.fn} precision={r.precision:.2f} recall={r.recall:.2f}"
            )
        if eval_out is not None:
            eval_out.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(eval_out, index=False, encoding="utf-8")


def _count(value: float | None) -> str:
    return "n/a" if value is None or pd.isna(value) else str(int(value))


def _fmt(value: float | None) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:.2f}"


@app.command()
def monitor(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: data.reference_date)."),
    ] = None,
    eval_out: Annotated[
        Path | None, typer.Option(help="Write the evaluation table to this CSV file.")
    ] = None,
) -> None:
    """Run the transaction-monitoring rules, store alerts and evaluate against ground truth."""
    s = get_settings()
    with get_db(s) as db:
        try:
            run = run_monitoring(db, s, as_of=as_of.date() if as_of else None)
        except MonitoringError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        evidence = db.query_df(
            f"SELECT rule_id, evidence FROM monitoring_runs WHERE run_id = {run.run_id}"
        )
        evidence_of = {
            str(r): int(e) for r, e in zip(evidence.iloc[:, 0], evidence.iloc[:, 1], strict=True)
        }
        for rule_id, alerts in run.by_rule.items():
            typer.echo(f"{rule_id:<22} alerts={alerts} evidence={evidence_of.get(rule_id, 0)}")
        typer.echo(
            f"run_id={run.run_id} as_of={run.as_of} alerts={run.alerts} evidence={run.evidence}"
        )
        if int(db.query_df("SELECT COUNT(*) AS n FROM ground_truth")["n"].iloc[0]) == 0:
            return
        table = evaluate_rules(db)
        for r in table.itertuples():
            typer.echo(
                f"{r.rule_id:<22} target_hits={_count(r.target_hits)} "
                f"other_suspicious={r.other_suspicious} benign={r.benign} "
                f"precision={_fmt(r.precision)} recall={_fmt(r.recall)} "
                f"precision_suspicious={_fmt(r.precision_suspicious)}"
            )
        for c in typology_coverage(db).itertuples():
            typer.echo(
                f"{c.typology:<16} scenarios={c.scenarios} flagged={c.flagged} "
                f"rate={c.rate:.2f} rules={c.rules or '-'}"
            )
        if eval_out is not None:
            eval_out.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(eval_out, index=False, encoding="utf-8")


@app.command()
def network(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: data.reference_date)."),
    ] = None,
    eval_out: Annotated[
        Path | None, typer.Option(help="Write the evaluation table to this CSV file.")
    ] = None,
) -> None:
    """Run the network detections (shared attributes, cycles, hubs), store alerts and evaluate."""
    s = get_settings()
    with get_db(s) as db:
        try:
            run = run_network(db, s, as_of=as_of.date() if as_of else None)
            evidence = db.query_df(
                f"SELECT rule_id, evidence FROM monitoring_runs WHERE run_id = {run.run_id}"
            )
            evidence_of = {
                str(r): int(e)
                for r, e in zip(evidence.iloc[:, 0], evidence.iloc[:, 1], strict=True)
            }
            for rule_id, alerts in run.by_rule.items():
                typer.echo(f"{rule_id:<22} alerts={alerts} evidence={evidence_of.get(rule_id, 0)}")
            typer.echo(
                f"run_id={run.run_id} as_of={run.as_of} alerts={run.alerts} "
                f"evidence={run.evidence} accounts={run.accounts} "
                f"active_accounts={run.active_accounts} "
                f"cycle_search_steps={run.cycle_search_steps}"
            )
            if int(db.query_df("SELECT COUNT(*) AS n FROM ground_truth")["n"].iloc[0]) == 0:
                return
            table = evaluate_network(db)
            coverage = network_coverage(db)
        except NetworkError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        for r in table.itertuples():
            typer.echo(
                f"{r.rule_id:<22} target_hits={_count(r.target_hits)} "
                f"other_suspicious={r.other_suspicious} benign={r.benign} "
                f"precision={_fmt(r.precision)} recall={_fmt(r.recall)} "
                f"precision_suspicious={_fmt(r.precision_suspicious)}"
            )
        for c in coverage.itertuples():
            typer.echo(
                f"{c.typology:<16} scenarios={c.scenarios} rule={c.flagged_rule} "
                f"network={c.flagged_network} any={c.flagged_any} new={c.new_by_network} "
                f"accounts={c.accounts} accounts_rule={c.accounts_rule} "
                f"accounts_network={c.accounts_network} accounts_any={c.accounts_any} "
                f"accounts_new={c.accounts_new} rules={c.rules or '-'}"
            )
        if eval_out is not None:
            eval_out.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(eval_out, index=False, encoding="utf-8")


def _echo_trace(result: TraceResult, limit: int) -> None:
    r = result.request
    typer.echo(
        f"method={result.method} backend={result.backend} account={r.account_id} "
        f"hops={r.hops} hours={r.hours} paths={result.n_paths} accounts={result.n_accounts} "
        f"cycles={result.n_cycles} seconds={result.seconds:.3f} query_lines={result.query_lines}"
    )
    for row in result.paths.head(limit).itertuples():
        flag = " CYCLE" if row.is_cycle else ""
        typer.echo(
            f"  hop={row.hop} {row.path} step_path={row.step_path} last_ts={row.last_ts} "
            f"amount_vnd={row.amount_vnd}{flag}"
        )
    if result.n_paths > limit:
        typer.echo(f"  ... {result.n_paths - limit} more path(s) not shown (--limit {limit})")


@app.command()
def trace(
    account: Annotated[str, typer.Option(help="Account id to trace money out of.")],
    hops: Annotated[
        int | None, typer.Option(help="Hops to follow (default: trace.default_hops).")
    ] = None,
    hours: Annotated[
        int | None, typer.Option(help="Hours from the first hop (default: trace.default_hours).")
    ] = None,
    method: Annotated[str, typer.Option(help="cte_raw, cte_edge, pgq, neo4j or all.")] = "cte_raw",
    since: Annotated[
        datetime | None,
        typer.Option(
            formats=["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"],
            help="The first hop must be at or after this time.",
        ),
    ] = None,
    min_amount: Annotated[
        int | None, typer.Option(help="cte_edge: ignore daily edges below this VND amount.")
    ] = None,
    top_k: Annotated[
        int | None, typer.Option(help="cte_edge: keep the k largest edges per account (0 = all).")
    ] = None,
    limit: Annotated[int, typer.Option(min=0, help="Path lines to print per method.")] = 20,
) -> None:
    """Trace money out of one account N hops within T hours with the chosen method(s)."""
    s = get_settings()
    with get_db(s) as db:
        names = list(METHODS) if method == "all" else [method]
        try:
            for name in names:
                if method == "all" and db.backend not in METHODS[name].backends:
                    typer.echo(f"method={name} skipped: Oracle only")
                    continue
                try:
                    result = run_trace(
                        db,
                        s,
                        account,
                        method=name,
                        hops=hops,
                        hours=hours,
                        since=since,
                        min_amount_vnd=min_amount,
                        top_k=top_k,
                    )
                except TraceUnavailableError as exc:
                    if method != "all":
                        raise
                    typer.echo(f"method={name} skipped: {exc}")
                    continue
                _echo_trace(result, limit)
        except TraceError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc


graph_app = typer.Typer(add_completion=False, help="Neo4j investigation projection.")
app.add_typer(graph_app, name="graph")


def _iso(value: datetime | None) -> str:
    return "-" if value is None else value.strftime("%Y-%m-%dT%H:%M:%S")


def _int_or_dash(value: int | None) -> str:
    return "-" if value is None else str(value)


def _source_db(s: Settings) -> Database:
    """Open the source database; an outage there must not be reported as a Neo4j outage."""
    try:
        return get_db(s)
    except ServiceUnavailableError as exc:
        typer.echo(f"source database not available: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@graph_app.command("sync")
def graph_sync(
    full: Annotated[bool, typer.Option("--full", help="Wipe and rebuild the whole graph.")] = False,
) -> None:
    """Sync the Neo4j projection from the system of record (incremental unless --full)."""
    s = get_settings()
    try:
        with _source_db(s) as db:
            run = run_sync(db, s, full=full, actor=ACTOR)
    except (SyncError, GraphError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except ServiceUnavailableError as exc:
        typer.echo(f"neo4j not available: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    nodes = sum(run.sent[k] for k in NODE_LABELS)
    rels = sum(run.sent[k] for k in REL_TYPES)
    typer.echo(
        f"run_id={run.run_id} mode={run.mode} source={run.source_backend} "
        f"since={_iso(run.since)} watermark={_iso(run.watermark_to)} nodes={nodes} rels={rels} "
        f"pruned={run.pruned} swept={run.swept} "
        f"lag_before_s={_int_or_dash(run.lag_before_seconds)} "
        f"lag_after_s={run.lag_after_seconds} seconds={run.seconds} in_sync={run.in_sync}"
    )
    for key in (*NODE_LABELS, *REL_TYPES):
        typer.echo(f"{key} sent={run.sent[key]} graph={run.graph[key]}")
    if not run.in_sync:
        typer.echo("OUT OF SYNC: run aml graph sync --full", err=True)


@graph_app.command("status")
def graph_status() -> None:
    """Show the watermark and element counts of the projection (read-only)."""
    s = get_settings()
    try:
        driver = open_driver(s)
    except ServiceUnavailableError as exc:
        typer.echo(f"neo4j not available: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        state = read_state(driver, s)
        if state is None:
            typer.echo("graph not synced: run aml graph sync", err=True)
            raise typer.Exit(code=1)
        counts = graph_counts(driver, s)
        last = client.run_read_file(driver, s, "read/sync_state.cypher").iloc[0]
    except GraphError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        driver.close()
    watermark, source = state
    lag = _graph_lag(watermark)
    typer.echo(
        f"watermark={_iso(watermark)} source={source} last_run_id={last.get('last_run_id', '-')} "
        f"lag_s={lag}"
    )
    for key in (*NODE_LABELS, *REL_TYPES):
        typer.echo(f"{key} {counts[key]}")


def _cell(value: object) -> str:
    if isinstance(value, list | tuple):
        return ",".join(str(v) for v in value)
    if hasattr(value, "tolist") and not isinstance(value, str):
        return _cell(value.tolist())
    return str(value)


@graph_app.command("query")
def graph_query(
    name: Annotated[str, typer.Argument(help=f"One of: {', '.join(QUERY_NAMES)}.")],
    account: Annotated[
        str | None, typer.Option(help="cycles, fan_in, fan_out: one account.")
    ] = None,
    customer: Annotated[
        str | None, typer.Option(help="shared_attributes, shared_cluster: a golden customer id.")
    ] = None,
    as_of: Annotated[
        datetime | None,
        typer.Option(
            formats=["%Y-%m-%d"],
            help="Only transfers up to this day (default: data.reference_date).",
        ),
    ] = None,
    limit: Annotated[int, typer.Option(min=0, help="Result rows to print.")] = 20,
) -> None:
    """Run one investigation query on the Neo4j projection (read-only; raises no alert)."""
    s = get_settings()
    try:
        with _source_db(s) as db:
            result = run_graph_query(
                db,
                s,
                name,
                account=account,
                customer=customer,
                as_of=as_of.date() if as_of else None,
                actor=ACTOR,
            )
    except QueryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    except ServiceUnavailableError as exc:
        typer.echo(f"neo4j not available: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except GraphError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"query={result.name} rows={result.n_rows} seconds={result.seconds:.3f} "
        f"query_lines={result.query_lines}"
    )
    typer.echo("  ".join(result.rows.columns))
    for row in result.rows.head(limit).itertuples(index=False):
        typer.echo("  ".join(_cell(v) for v in row))


@graph_app.command("gds")
def graph_gds(
    as_of: Annotated[
        datetime | None,
        typer.Option(
            formats=["%Y-%m-%d"],
            help="Only transfers up to this day (default: data.reference_date).",
        ),
    ] = None,
) -> None:
    """Compute GDS features (WCC, Louvain, PageRank, degree) and store them (raises no alert)."""
    s = get_settings()
    try:
        with _source_db(s) as db:
            run = run_gds(db, s, as_of=as_of.date() if as_of else None, actor=ACTOR)
    except ServiceUnavailableError as exc:
        typer.echo(f"neo4j not available: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except GraphError as exc:  # includes GdsError
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"run_id={run.run_id} as_of={run.as_of.isoformat()} accounts={run.accounts} "
        f"active={run.active_accounts} wcc_components={run.wcc_components} "
        f"louvain_communities={run.louvain_communities} shared_clusters={run.shared_clusters} "
        f"seconds={run.seconds} gds={run.gds_version}"
    )
    for name, (nodes, rels) in run.graphs.items():
        typer.echo(f"{name} nodes={nodes} relationships={rels}")


def _graph_lag(watermark: datetime | None) -> str:
    """Seconds between the newest source transaction and the watermark (reads the source)."""
    s = get_settings()
    try:
        with get_db(s) as db:
            latest = source_stats(db).last_ts
    except Exception:  # status stays usable when the source cannot be read
        return "-"
    if latest is None or watermark is None:
        return "-"
    return str(max(0, int((latest - watermark).total_seconds())))


cases_app = typer.Typer(add_completion=False, help="Case consolidation and decisions.")
app.add_typer(cases_app, name="cases")


@cases_app.command("build")
def cases_build(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: data.reference_date)."),
    ] = None,
) -> None:
    """Group the alerts into cases per golden customer, enrich them and store a new run."""
    s = get_settings()
    with get_db(s) as db:
        try:
            run = run_cases(db, s, as_of=as_of.date() if as_of else None, actor=ACTOR)
        except CaseError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    typer.echo(
        f"run_id={run.run_id} as_of={run.as_of} items={run.items} alerts={run.alerts} "
        f"suppressed={run.suppressed} active={run.active} cases={run.cases} opened={run.opened} "
        f"reopened={run.reopened} closed={run.closed} graph_features={run.graph_source}"
    )
    for rule, count in run.suppressed_by_rule.items():  # no `run_id=`: one summary line only
        typer.echo(f"{rule} suppressed={count}")


@cases_app.command("suppressed")
def cases_suppressed(
    limit: Annotated[int | None, typer.Option(help="Show at most this many items.")] = None,
) -> None:
    """List the items the latest run suppressed, each with the rule and its reason."""
    s = get_settings()
    with get_db(s) as db:
        try:
            total, items = list_suppressed(db, limit=limit)
        except CaseError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    typer.echo(f"{total} suppressed item(s)")
    for i in items:
        typer.echo(f"  {i.item_key} {i.suppression_rule} {i.suppression_reason}")


@cases_app.command("show")
def cases_show(
    case_id: Annotated[str, typer.Argument(help="Case id, e.g. C-CIF00000189-20260413.")],
) -> None:
    """Show one case of the latest run: alerts first, then one JSON line per enrichment block."""
    s = get_settings()
    with get_db(s) as db:
        try:
            view = load_case(db, case_id)
        except CaseError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    typer.echo(f"{view.case_id} {view.status} {view.golden_customer_id} alerts={len(view.alerts)}")
    if view.disposition is not None:
        d = view.disposition
        typer.echo(f"disposition={d.disposition} actor={d.actor} decided_on={d.decided_on}")
    for a in view.alerts:
        typer.echo(
            f"  {a.event_ts:%Y-%m-%d %H:%M:%S} {a.source} {a.rule_id} cif={a.cif} "
            f"amount_vnd={a.amount_vnd} {a.item_key}"
        )
    for section, content in view.enrichment.items():
        typer.echo(f"{section} {json.dumps(content, ensure_ascii=True)}")


@cases_app.command("summary")
def cases_summary(
    case_id: Annotated[str | None, typer.Argument(help="Case to summarise.")] = None,
    out: Annotated[
        Path | None, typer.Option(help="Write the markdown to this file instead of stdout.")
    ] = None,
    all_cases: Annotated[
        bool, typer.Option("--all", help="Summarise every case of the current run.")
    ] = False,
    out_dir: Annotated[
        Path | None, typer.Option(help="Directory for --all: one <case_id>.md per case.")
    ] = None,
) -> None:
    """Templated markdown summary of a case (no LLM). Reads only: nothing is stored or audited."""
    if all_cases == (case_id is not None) or (all_cases and out_dir is None):
        typer.echo("give a CASE_ID, or --all together with --out-dir", err=True)
        raise typer.Exit(code=2)
    s = get_settings()
    with get_db(s) as db:
        try:
            if all_cases and out_dir is not None:
                written = write_summaries(db, s, out_dir)
                typer.echo(f"wrote {written} summaries to {out_dir}")
                return
            data = as_file_bytes(summarize(db, s, str(case_id)).markdown)
        except (CaseError, NarrativeError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        except OSError as exc:  # e.g. --out-dir names an existing file
            typer.echo(f"cannot write to {out_dir}: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    if out is not None:
        try:
            out.write_bytes(data)
        except OSError as exc:  # e.g. the parent directory does not exist
            typer.echo(f"cannot write to {out}: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(f"wrote {out}")
        return
    # bytes, not text: a Windows console code page cannot encode Vietnamese names
    sys.stdout.flush()
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _check_disposition(value: str) -> str:
    if value not in DISPOSITIONS:
        raise typer.BadParameter(f"must be one of {', '.join(DISPOSITIONS)}")
    return value


@cases_app.command("dispose")
def cases_dispose(
    case_id: Annotated[str, typer.Argument(help="Case id to decide on.")],
    disposition: Annotated[
        str,
        typer.Option(help=f"One of {', '.join(DISPOSITIONS)}.", callback=_check_disposition),
    ],
    reason: Annotated[str, typer.Option(help="Why (required).")],
    actor: Annotated[str, typer.Option(help="The person who decides (not the system actor).")],
    decided_on: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Decision date (default: data.reference_date)."),
    ] = None,
) -> None:
    """Record a human decision on a case; the next `aml cases build` sets the case status."""
    s = get_settings()
    with get_db(s) as db:
        try:
            disposition_id = record_disposition(
                db,
                s,
                case_id,
                disposition,
                reason=reason,
                actor=actor,
                decided_on=decided_on.date() if decided_on else None,
            )
        except CaseError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
    typer.echo(f"disposition_id={disposition_id} case_id={case_id} disposition={disposition}")


def _check_kind(value: str | None) -> str | None:
    if value is not None and value not in KINDS:
        raise typer.BadParameter(f"must be one of {', '.join(KINDS)}")
    return value


def _write_json(path: Path | None, payload: dict[str, object]) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


@cases_app.command("label")
def cases_label(
    fraction: Annotated[
        float | None, typer.Option(min=0.0, max=1.0, help="Share of case groups (0, 1].")
    ] = None,
) -> None:
    """Record SIMULATED dispositions from the ground truth on a seeded share of the case groups."""
    s = get_settings()
    if fraction is not None:
        if fraction <= 0:
            raise typer.BadParameter("fraction must be in (0, 1]")
        cfg = s.cases.prioritization.model_copy(update={"simulate_fraction": fraction})
        s = s.model_copy(update={"cases": s.cases.model_copy(update={"prioritization": cfg})})
    with get_db(s) as db:
        try:
            sim = simulate_dispositions(db, s)
        except (CaseError, PrioritizationError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    typer.echo(f"run_id={sim.run_id} groups={sim.groups} {label_line(sim)}")


@cases_app.command("train")
def cases_train(
    model: Annotated[
        str | None, typer.Option(help="logreg or lightgbm.", callback=_check_kind)
    ] = None,
    eval_out: Annotated[Path | None, typer.Option(help="Write the metrics as JSON.")] = None,
) -> None:
    """Train a ranking model on the decided cases and store it as a new version."""
    s = get_settings()
    with get_db(s) as db:
        try:
            run = train(db, s, kind=model, actor=ACTOR)
        except (CaseError, PrioritizationError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    typer.echo(train_line(run))
    typer.echo(NOTE)
    _write_json(eval_out, {"model": {"version": run.version, "kind": run.kind}, "cv": run.metrics})


@app.command()
def score(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: data.reference_date)."),
    ] = None,
    top: Annotated[int, typer.Option(min=0, help="Queue lines to show.")] = 10,
    eval_out: Annotated[Path | None, typer.Option(help="Write model, cv, holdout as JSON.")] = None,
) -> None:
    """Build cases, simulate decisions, train and score: rank the queue (it never closes a case)."""
    s = get_settings()
    with get_db(s) as db:
        try:
            payload = run_chain(
                db, s, as_of=as_of.date() if as_of else None, top=top, emit=typer.echo
            )
        except (CaseError, PrioritizationError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    _write_json(eval_out, payload)


@app.command()
def bench(
    profile: Annotated[
        str | None,
        typer.Option(help="Label of the data (default: from the newest LOADED audit row)."),
    ] = None,
    report_only: Annotated[
        bool,
        typer.Option("--report-only", help="Only rebuild the report and chart from result files."),
    ] = False,
) -> None:
    """Time the four fund-flow traces on the data as it is; write the result file and report."""
    s = get_settings()
    out = s.path(s.bench.results_dir)
    try:
        if report_only:
            for path in write_report(out):
                typer.echo(f"wrote {path}")
            return
        out.mkdir(parents=True, exist_ok=True)
        with _source_db(s) as db:
            result = run_bench(db, s, profile=profile, command=_command_line(), actor=ACTOR)
        written = write_result(result, out)
        report, chart = write_report(out)
    except BenchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    meta, cells = result.meta, result.cells
    counts = {k: sum(c.status == k for c in cells) for k in ("ok", "skipped", "error")}
    typer.echo(
        f"bench profile={meta['profile']} backend={meta['backend']} "
        f"accounts={','.join(meta['params']['accounts'])} cells={len(cells)} "
        f"ok={counts['ok']} skipped={counts['skipped']} error={counts['error']} "
        f"seconds={meta['total_seconds']}"
    )
    shown: set[tuple[str, str]] = set()
    for cell in cells:
        if cell.status != STATUS_OK and (cell.method, cell.status) not in shown:
            shown.add((cell.method, cell.status))
            typer.echo(f"method={cell.method} {cell.status}: {cell.reason}")
    for mismatch in path_mismatches(result):
        typer.echo(f"warning: the exact methods disagree on the paths ({mismatch})", err=True)
    for path in (written, report, chart):
        typer.echo(f"wrote {path}")


def _command_line() -> str:
    """The command as the user typed it, for the provenance block of a result file."""
    return " ".join(["aml", *sys.argv[1:]]) if sys.argv[1:2] == ["bench"] else "aml bench"


def _not_yet(phase: int) -> None:
    typer.echo(f"Not implemented yet - arrives in Phase {phase}.", err=True)
    raise typer.Exit(code=1)


app.add_typer(memo_app, name="memo")  # Phase 8d: the commands live in aml.memo.cli

rag_app = typer.Typer(add_completion=False, help="Knowledge layer for the assistant (Phase 8).")
app.add_typer(rag_app, name="rag")


@rag_app.command("build")
def rag_build(
    full: Annotated[
        bool, typer.Option("--full", help="Wipe and rebuild the knowledge layer.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only read the documents and print the counts.")
    ] = False,
) -> None:
    """Build the knowledge layer in Neo4j from docs/knowledge/ and the cases."""
    if dry_run and full:
        typer.echo("--dry-run cannot be combined with --full", err=True)
        raise typer.Exit(code=2)
    s = get_settings()
    try:
        if dry_run:
            out, err = [rag_cli.dry_run_line(s)], []
        else:
            out, err = rag_cli.build_lines(s, full=full, actor=ACTOR)
    except (KnowledgeError, LLMError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except OllamaUnavailableError as exc:
        typer.echo(f"ollama not available: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ServiceUnavailableError as exc:
        typer.echo(f"neo4j not available: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for line in out:
        typer.echo(line)
    for line in err:
        typer.echo(line, err=True)


@rag_app.command("status")
def rag_status() -> None:
    """Show what the knowledge layer holds and whether it is up to date (read-only)."""
    try:
        lines = rag_cli.status_lines(get_settings())
    except (KnowledgeError, LLMError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except ServiceUnavailableError as exc:
        typer.echo(f"neo4j not available: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for line in lines:
        typer.echo(line)


@rag_app.command("retrieve")
def rag_retrieve(
    question: Annotated[str, typer.Argument(help="The question to retrieve evidence for.")],
    case_id: Annotated[
        str | None, typer.Option("--case", help="Case the question is about.")
    ] = None,
    mode: Annotated[
        str, typer.Option(help="graphrag (router picks the retrievers) or vector (chunks only).")
    ] = "graphrag",
) -> None:
    """Show the evidence the assistant would be given for a question (read-only, no answer)."""
    try:
        text = rag_cli.retrieve_text(
            get_settings(), question, case_id=case_id, mode=mode, actor=ACTOR
        )
    except RetrievalUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except RetrievalError as exc:  # bad input: empty question, unknown mode or customer
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    except CaseError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except GraphError as exc:  # a server timeout or error of a graph read
        typer.echo(f"graph query failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ServiceUnavailableError as exc:
        typer.echo(f"database not available: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    # bytes, not text: a Windows console code page cannot encode Vietnamese
    sys.stdout.flush()
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


@rag_app.command("eval")
def rag_eval(
    golden_only: Annotated[
        bool, typer.Option("--golden-only", help="Only build and write the golden set.")
    ] = False,
    report_only: Annotated[
        bool, typer.Option("--report-only", help="Only rebuild the report from eval_result.json.")
    ] = False,
    limit: Annotated[
        int | None, typer.Option("--limit", min=1, help="Ask only the first N questions.")
    ] = None,
    types: Annotated[
        list[str] | None, typer.Option("--type", help="Question type to ask (repeatable).")
    ] = None,
    modes: Annotated[
        list[str] | None, typer.Option("--mode", help="Retrieval mode to ask in (repeatable).")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Ask again even when an answer is stored.")
    ] = False,
) -> None:
    """Evaluate the assistant on the golden set: five deterministic metrics per retrieval mode."""
    try:
        eval_cli.check_arguments(types or [], modes or [])
    except EvalError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if golden_only and report_only:
        typer.echo("--golden-only cannot be combined with --report-only", err=True)
        raise typer.Exit(code=2)
    s = get_settings()
    err: list[str] = []
    try:
        if golden_only:
            out = eval_cli.golden_lines(s)
        elif report_only:
            out = eval_cli.report_lines(s)
        else:
            out, err = eval_cli.eval_lines(
                s,
                limit=limit,
                types=types or [],
                modes=modes or [],
                force=force,
                command=_rag_eval_command_line(),
                actor=ACTOR,
            )
    except (GoldenError, EvalError, KnowledgeError, LLMError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except OllamaUnavailableError as exc:
        typer.echo(f"ollama not available: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ServiceUnavailableError as exc:
        typer.echo(f"neo4j not available: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for line in out:
        typer.echo(line)
    for line in err:  # only SIDE EFFECTS: a decision table changed during a read-only run
        typer.echo(line, err=True)
    if err:
        raise typer.Exit(code=1)


def _rag_eval_command_line() -> str:
    """The command as the user typed it, for the provenance block of the result file."""
    typed = sys.argv[1:3] == ["rag", "eval"]
    return " ".join(["aml", *sys.argv[1:]]) if typed else "aml rag eval"


for _name, _phase in {
    "ui": 9,
}.items():  # fmt: skip
    app.command(_name, help=f"(Phase {_phase})")(lambda p=_phase: _not_yet(p))


if __name__ == "__main__":
    app()
