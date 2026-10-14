"""The `aml models` command group: card and audit-check.

`aml.cli` only mounts this group. Neither command touches a customer, a case or a hit: the first
writes Markdown files and its own audit rows, the second only reads the audit trail.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from aml.cases.chain import ACTOR
from aml.common.config import get_settings
from aml.common.db import get_db
from aml.governance.audit_check import check_versions
from aml.governance.cards import MODEL_CARDS, write_cards

models_app = typer.Typer(
    add_completion=False,
    help="Model cards and the model-version check on the audit trail (Phase 7b-iii).",
)


def _check_model(value: str | None) -> str | None:
    if value is not None and value not in MODEL_CARDS:
        raise typer.BadParameter(f"must be one of {', '.join(MODEL_CARDS)}")
    return value


@models_app.command("card")
def models_card(
    model: Annotated[
        str | None, typer.Option(help="One model card only.", callback=_check_model)
    ] = None,
    out: Annotated[
        Path | None, typer.Option(help="Directory of the cards (default: ml.governance.cards_dir).")
    ] = None,
    check: Annotated[
        bool, typer.Option("--check", help="Write nothing; exit 1 if a card is missing or stale.")
    ] = False,
) -> None:
    """Write the model card of each model from what it stored; skip a model with nothing stored."""
    s = get_settings()
    names = [model] if model else list(s.ml.governance.models)
    target = out if out is not None else s.path(s.ml.governance.cards_dir)
    with get_db(s) as db:
        report = write_cards(db, s, out_dir=out, names=names, check=check, actor=ACTOR)
    skipped = {item.name: item.reason for item in report.skipped}
    for name in names:
        path = target / f"{name}.md"
        if name in skipped:
            typer.echo(f"skipped {name}: {skipped[name]}")
        elif check:
            typer.echo(f"{'stale' if str(path) in report.stale else 'current'} {name}: {path}")
        else:
            note = "" if str(path) in report.written else " (unchanged)"
            typer.echo(f"card {name} -> {path}{note}")
    if (model and model in skipped) or report.stale:
        raise typer.Exit(code=1)


@models_app.command("audit-check")
def models_audit_check(
    since: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Only audit rows from this day (UTC) on."),
    ] = None,
) -> None:
    """Check that every audit row holding a model's output names the model version."""
    s = get_settings()
    with get_db(s) as db:
        checked, gaps = check_versions(db, since=since)
    for gap in gaps:
        typer.echo(f"{gap.module}/{gap.decision} {gap.entity_id} {gap.problem}")
    if gaps:
        raise typer.Exit(code=1)
    typer.echo(f"audit versions ok: {checked} row(s) checked")
