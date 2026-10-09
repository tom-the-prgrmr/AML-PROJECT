"""Single command-line entry point: ``uv run aml <command>``.

The Makefile and ``tasks.ps1`` are thin wrappers around these commands so the project
runs the same way on Linux/macOS and on Windows without ``make``.
"""

from __future__ import annotations

import logging

import typer

from aml.common.audit import audit
from aml.common.config import get_settings
from aml.common.db import get_db
from aml.common.services import all_statuses

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


def _not_yet(phase: int) -> None:
    typer.echo(f"Not implemented yet - arrives in Phase {phase}.", err=True)
    raise typer.Exit(code=1)


for _name, _phase in {
    "data": 1, "load": 1, "screen": 3, "er": 4, "monitor": 5, "graph": 6,
    "bench": 6, "score": 7, "rag": 8, "ui": 9,
}.items():  # fmt: skip
    app.command(_name, help=f"(Phase {_phase})")(lambda p=_phase: _not_yet(p))


if __name__ == "__main__":
    app()
