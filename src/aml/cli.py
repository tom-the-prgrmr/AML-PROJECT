"""Single command-line entry point: ``uv run aml <command>``.

The Makefile and ``tasks.ps1`` are thin wrappers around these commands so the project
runs the same way on Linux/macOS and on Windows without ``make``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from aml.common.audit import audit
from aml.common.config import get_settings
from aml.common.db import Database, get_db
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


def _not_yet(phase: int) -> None:
    typer.echo(f"Not implemented yet - arrives in Phase {phase}.", err=True)
    raise typer.Exit(code=1)


for _name, _phase in {
    "monitor": 5, "graph": 6,
    "bench": 6, "score": 7, "rag": 8, "ui": 9,
}.items():  # fmt: skip
    app.command(_name, help=f"(Phase {_phase})")(lambda p=_phase: _not_yet(p))


if __name__ == "__main__":
    app()
