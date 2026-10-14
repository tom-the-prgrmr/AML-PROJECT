"""The `aml screen-ml` command group: label, train, score and run.

`aml.cli` only mounts this group. None of the commands changes a screening result: the model
ranks hits, and a person decides them.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import typer

from aml.common.config import Settings, get_settings
from aml.common.db import Database, get_db
from aml.screening.ml.labels import LabelSimulation, simulate_labels
from aml.screening.ml.model import ScreeningMlError
from aml.screening.ml.pipeline import (
    MatchScoringRun,
    MatchTrainingRun,
    score,
    train,
)
from aml.screening.ml.store import run_query

screen_ml_app = typer.Typer(
    add_completion=False,
    help="Learned screening-hit model (Phase 7b-ii): simulated labels, training, ranking.",
)

RANKING_ONLY = "ranking only: no screening hit was cleared or closed by the model"
DEFAULT_TOP = 10


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code=1)


def _fraction(value: float | None) -> float | None:
    if value is not None and not 0 < value <= 1:
        raise typer.BadParameter("must be in (0, 1]")
    return value


FractionOption = Annotated[
    float | None,
    typer.Option(
        help="Share of the watchlist entries to label (default: ml.screening.simulate_fraction).",
        callback=_fraction,
    ),
]
TopOption = Annotated[int, typer.Option(min=0, help="How many best-ranked hits to print.")]


def _settings(fraction: float | None) -> Settings:
    s = get_settings()
    if fraction is None:
        return s
    cfg = s.ml.screening.model_copy(update={"simulate_fraction": fraction})
    return s.model_copy(update={"ml": s.ml.model_copy(update={"screening": cfg})})


def _f(value: Any) -> str:
    return "-" if value is None else f"{value}"


def _labels_line(sim: LabelSimulation) -> str:
    return (
        f"labels groups={sim.groups} labelled_groups={sim.labelled_groups} "
        f"labelled={sim.labelled} TRUE_MATCH={sim.true_match} FALSE_MATCH={sim.false_match} "
        f"held_out={sim.held_out} skipped={sim.skipped}"
    )


def _model_line(t: MatchTrainingRun) -> str:
    return (
        f"model version={t.version} pairs={t.pairs} TRUE_MATCH={t.true_match} "
        f"FALSE_MATCH={t.false_match} human={t.human_labels} "
        f"roc_auc={t.metrics['roc_auc']} pr_auc={t.metrics['pr_auc']}"
    )


def _comparison_lines(kind: str, rows: list[dict[str, Any]]) -> list[str]:
    return [
        f"{kind} {r['baseline']} pairs={r['pairs']} positives={r['positives']} "
        f"rule_flagged={r['rule_flagged']} rule_precision={_f(r['rule_precision'])} "
        f"model_flagged={r['model_flagged']} model_precision={_f(r['model_precision'])} "
        f"recall={_f(r['model_recall'])} reduction={_f(r['flagged_reduction_pct'])}"
        for r in rows
    ]


def _echo_training(t: MatchTrainingRun) -> None:
    typer.echo(_model_line(t))
    for line in _comparison_lines("cv", t.metrics["comparison"]):
        typer.echo(line)


def _echo_scoring(db: Database, run: MatchScoringRun, top: int) -> None:
    for line in _comparison_lines("holdout", run.holdout):
        typer.echo(line)
    typer.echo(f"scored pairs={run.scored} model={run.version}")
    ranked = run_query(db, "top_scores", score_run_id=run.score_run_id, top=top)
    for r in ranked.itertuples():
        names = ",".join(t["feature"] for t in json.loads(str(r.top_features)))
        typer.echo(f"{r.score_rank} {r.score:.6f} {r.cif}:{r.entry_id} {r.decision} top={names}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


@screen_ml_app.command("label")
def screen_ml_label(fraction: FractionOption = None) -> None:
    """Simulate investigator labels from the ground truth on a seeded share of the entries."""
    s = _settings(fraction)
    with get_db(s) as db:
        try:
            typer.echo(_labels_line(simulate_labels(db, s)))
        except ScreeningMlError as exc:
            raise _fail(str(exc)) from exc


@screen_ml_app.command("train")
def screen_ml_train() -> None:
    """Train the model on the labelled pairs and store it with its training set."""
    s = get_settings()
    with get_db(s) as db:
        try:
            _echo_training(train(db, s))
        except ScreeningMlError as exc:
            raise _fail(str(exc)) from exc


@screen_ml_app.command("score")
def screen_ml_score(top: TopOption = DEFAULT_TOP) -> None:
    """Score every current hit with the newest model; the Tier 2 decision stays as it is."""
    s = get_settings()
    with get_db(s) as db:
        try:
            _echo_scoring(db, score(db, s), top)
        except ScreeningMlError as exc:
            raise _fail(str(exc)) from exc
    typer.echo(RANKING_ONLY)


@screen_ml_app.command("run")
def screen_ml_run(
    fraction: FractionOption = None,
    top: TopOption = DEFAULT_TOP,
    eval_out: Annotated[
        Path | None, typer.Option(help="Write the model and both comparisons as JSON.")
    ] = None,
) -> None:
    """label, then train, then score, then print the comparison with the fixed thresholds."""
    s = _settings(fraction)
    with get_db(s) as db:
        try:
            typer.echo(_labels_line(simulate_labels(db, s)))
            trained = train(db, s)
            _echo_training(trained)
            scored = score(db, s, model_id=trained.model_id)
            _echo_scoring(db, scored, top)
        except ScreeningMlError as exc:
            raise _fail(str(exc)) from exc
    if eval_out is not None:
        model = {k: v for k, v in asdict(trained).items() if k != "metrics"}
        model["metrics"] = {k: v for k, v in trained.metrics.items() if k != "comparison"}
        _write_json(
            eval_out,
            {"model": model, "cv": trained.metrics["comparison"], "holdout": scored.holdout},
        )
    typer.echo(RANKING_ONLY)
