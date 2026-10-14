"""The `aml anomaly` command group: run and eval.

`aml.cli` only mounts this group. Neither command touches a case: the model raises signals for a
person to review and closes, clears and suppresses nothing.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from aml.common.config import get_settings
from aml.common.db import Database, get_db
from aml.ml.anomaly.evaluate import anomaly_coverage, evaluate_anomaly
from aml.ml.anomaly.runner import AnomalyError, run_anomaly

anomaly_app = typer.Typer(
    add_completion=False,
    help="Isolation forest per customer-month (Phase 7b-i): a fourth alert source, signals only.",
)

SIGNALS_ONLY = "anomaly alerts are signals for review: no case is closed or cleared by this model"
EVAL_NAME = "anomaly_eval.json"


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code=1)


def _has_ground_truth(db: Database) -> bool:
    return int(db.query_df("SELECT COUNT(*) FROM ground_truth").iloc[0, 0]) > 0


def _write_json(path: Path, command: str, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"command": command, **result}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _coverage_lines(db: Database) -> list[str]:
    return [
        f"{c.typology:<16} scenarios={c.scenarios} rules={c.flagged_rules} "
        f"anomaly={c.flagged_anomaly} new={c.new_by_anomaly} accounts={c.accounts} "
        f"accounts_rules={c.accounts_rules} accounts_anomaly={c.accounts_anomaly} "
        f"accounts_new={c.accounts_new}"
        for c in anomaly_coverage(db).itertuples()
    ]


def _command(name: str, as_of: datetime | None, eval_out: Path | None) -> str:
    """The command as the user typed it, for the provenance of a result file.

    Under a test runner ``sys.argv`` is not the typed command, so it is rebuilt from the options.
    """
    if sys.argv[1:3] == ["anomaly", name]:
        return " ".join(["aml", *sys.argv[1:]])
    parts = ["aml", "anomaly", name]
    if eval_out is not None:
        parts += ["--eval-out", str(eval_out)]
    if as_of is not None:
        parts += ["--as-of", as_of.date().isoformat()]
    return " ".join(parts)


@anomaly_app.command("run")
def anomaly_run(
    as_of: Annotated[
        datetime | None,
        typer.Option(formats=["%Y-%m-%d"], help="Reference date (default: data.reference_date)."),
    ] = None,
    eval_out: Annotated[
        Path | None, typer.Option(help="Write the evaluation against the ground truth as JSON.")
    ] = None,
) -> None:
    """Score every customer-month, store the scores and alert on the top fraction."""
    s = get_settings()
    with get_db(s) as db:
        try:
            run = run_anomaly(db, s, as_of=as_of.date() if as_of else None)
            typer.echo(
                f"run_id={run.run_id} model_version={run.model_version} as_of={run.as_of} "
                f"samples={run.samples} customers={run.customers} months={run.months} "
                f"alerts={run.alerts} threshold={run.threshold:.4f} "
                f"graph_source={run.graph_source} monitoring_run_id={run.monitoring_run_id}"
            )
            has_truth = _has_ground_truth(db)
            if eval_out is not None and not has_truth:
                typer.echo(
                    f"no ground truth: no evaluation JSON was written to {eval_out}", err=True
                )
            if has_truth:
                for line in _coverage_lines(db):
                    typer.echo(line)
                if eval_out is not None:
                    _write_json(eval_out, _command("run", as_of, eval_out), evaluate_anomaly(db, s))
        except AnomalyError as exc:
            raise _fail(str(exc)) from exc
    typer.echo(SIGNALS_ONLY)


@anomaly_app.command("eval")
def anomaly_eval(
    eval_out: Annotated[
        Path | None, typer.Option(help="JSON result (default: <results_dir>/anomaly_eval.json).")
    ] = None,
) -> None:
    """Measure the current anomaly run against the ground truth; stores nothing in the database."""
    s = get_settings()
    path = eval_out or s.path(s.ml.anomaly.results_dir) / EVAL_NAME
    with get_db(s) as db:
        try:
            result = evaluate_anomaly(db, s)
            lines = _coverage_lines(db)
        except AnomalyError as exc:
            raise _fail(str(exc)) from exc
    _write_json(path, _command("eval", None, eval_out), result)
    for line in lines:
        typer.echo(line)
    typer.echo(f"wrote {path}")
    typer.echo(SIGNALS_ONLY)
