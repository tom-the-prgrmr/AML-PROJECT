"""The `aml score` chain: build cases, simulate decisions, rebuild, train, score, report.

Each step prints one line as soon as it is done (``emit``), so a step that fails leaves the lines of
the steps before it on screen, and what those steps wrote stays in the database. The model only
ranks: the last line of a successful run says so.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from aml.cases.labels import Simulation, simulate_dispositions
from aml.cases.prioritize import ScoringRun, TrainingRun, score, train
from aml.cases.runner import CaseRun, run_cases
from aml.cases.values import lower_columns
from aml.common.config import Settings
from aml.common.db import Database

__all__ = ["ACTOR", "LAST_LINE", "NOTE", "eval_payload", "label_line", "run_chain", "train_line"]

LAST_LINE = "ranking only: no case was closed or cleared by the model"
ACTOR = "cli"  # the actor of every automated step started from the command line
NOTE = "note metrics cover alerted cases only; below-the-line customers are not sampled (Phase 7b)"
POPULATION = "alerted cases only; below-the-line customers are not sampled (Phase 7b)"


def _f(value: float | None) -> str:
    return "-" if value is None else f"{value}"


def _metrics(m: dict[str, Any]) -> str:
    return f"roc_auc={_f(m.get('roc_auc'))} pr_auc={_f(m.get('pr_auc'))} " + (
        f"prevalence={_f(m.get('prevalence'))}"
    )


def label_line(sim: Simulation) -> str:
    return (
        f"labelled={sim.labelled} SUSPICIOUS={sim.suspicious} FALSE_POSITIVE={sim.false_positive} "
        f"held_out={sim.held_out} skipped={sim.skipped}"
    )


def train_line(t: TrainingRun) -> str:
    return f"version={t.version} cases={t.cases} {_metrics(t.metrics)}"


def _cases_line(run: CaseRun) -> str:
    return (
        f"cases run_id={run.run_id} as_of={run.as_of} cases={run.cases} opened={run.opened} "
        f"reopened={run.reopened} closed={run.closed} suppressed={run.suppressed}"
    )


def _queue_lines(db: Database, top: int) -> list[str]:
    """The first ``top`` cases of the queue as ``rank score case_id top=f1,f2,f3``."""
    df = lower_columns(
        db.query_df("SELECT case_id, score, queue_rank, top_features FROM case_queue")
    )
    ranked = sorted(
        zip(df["queue_rank"], df["case_id"], df["score"], df["top_features"], strict=True)
    )
    lines = []
    for rank, case_id, value, raw in ranked[: max(top, 0)]:
        names = ",".join(t["feature"] for t in json.loads(str(raw))[:3])
        lines.append(f"{int(rank)} {float(value):.4f} {case_id} top={names}")
    return lines


def eval_payload(t: TrainingRun, s: ScoringRun, settings: Settings) -> dict[str, Any]:
    """The content of ``--eval-out``: the model, its cross-validation and the holdout.

    A CLI test pins the top-level keys, so ``population`` sits inside ``cv`` and ``holdout``.
    """
    return {
        "model": {
            "version": t.version,
            "kind": t.kind,
            "model_id": t.model_id,
            "seed": settings.seed,
            "cases": t.cases,
            "suspicious": t.suspicious,
            "false_positive": t.false_positive,
        },
        "cv": t.metrics | {"population": POPULATION},
        "holdout": s.holdout | {"population": POPULATION},
    }


def run_chain(
    db: Database,
    settings: Settings,
    *,
    as_of: date | None,
    top: int,
    emit: Callable[[str], None],
) -> dict[str, Any]:
    """Run the whole Phase 7 chain; return the ``--eval-out`` payload.

    Raises `CaseError` or `PrioritizationError` at the first step that cannot run.
    """
    emit(_cases_line(run_cases(db, settings, as_of=as_of, actor=ACTOR)))
    if settings.cases.prioritization.simulate_dispositions:
        sim = simulate_dispositions(db, settings)
        emit(f"labels {label_line(sim)}")
        emit(_cases_line(run_cases(db, settings, as_of=as_of, actor=ACTOR)))
    trained = train(db, settings, actor=ACTOR)
    emit(f"model {train_line(trained)}")
    scored = score(db, settings, actor=ACTOR)
    emit(
        f"scored cases={scored.cases} queue={scored.queue} model={scored.version} "
        f"score_run_id={scored.score_run_id}"
    )
    h = scored.holdout
    emit(f"holdout n={h.get('n', 0)} {_metrics(h)} population=alerted-cases-only")
    for line in _queue_lines(db, top):
        emit(line)
    emit(NOTE)
    emit(LAST_LINE)
    return eval_payload(trained, scored, settings)
