"""Single command-line entry point: ``uv run aml <command>``.

The Makefile and ``tasks.ps1`` are thin wrappers around these commands so the project
runs the same way on Linux/macOS and on Windows without ``make``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from aml.common.audit import audit
from aml.common.config import get_settings
from aml.common.db import get_db
from aml.common.services import all_statuses
from aml.datagen.load import LoadError, load_parquet, read_manifest
from aml.datagen.pipeline import run_pipeline

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
        n = db.run_named_script("ddl/000_audit_log.sql")
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
