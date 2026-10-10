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
from aml.common.db import get_db
from aml.common.services import all_statuses
from aml.datagen.load import LoadError, load_parquet, read_manifest
from aml.datagen.pipeline import run_pipeline
from aml.dba.plans import explain_plan, pruning_queries
from aml.dba.schema import apply_schema
from aml.dba.security import SecurityConfigError, apply_security
from aml.dq.runner import label_agreement, run_dq

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


def _not_yet(phase: int) -> None:
    typer.echo(f"Not implemented yet - arrives in Phase {phase}.", err=True)
    raise typer.Exit(code=1)


for _name, _phase in {
    "screen": 3, "er": 4, "monitor": 5, "graph": 6,
    "bench": 6, "score": 7, "rag": 8, "ui": 9,
}.items():  # fmt: skip
    app.command(_name, help=f"(Phase {_phase})")(lambda p=_phase: _not_yet(p))


if __name__ == "__main__":
    app()
