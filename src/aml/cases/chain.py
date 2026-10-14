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

from aml.cases.btl import BtlSample, draw_sample
from aml.cases.btl_model import BtlEvaluation, evaluate_btl, train_with_btl
from aml.cases.labels import Simulation, simulate_dispositions
from aml.cases.model import PrioritizationError
from aml.cases.prio_store import NO_MODEL
from aml.cases.prioritize import ScoringRun, TrainingRun, score, train
from aml.cases.runner import CaseRun, run_cases
from aml.cases.values import lower_columns
from aml.common.config import Settings
from aml.common.db import Database

__all__ = [
    "ACTOR",
    "BTL_LAST_LINE",
    "LAST_LINE",
    "NOTE",
    "btl_eval_line",
    "btl_line",
    "eval_payload",
    "evaluation_payload",
    "label_line",
    "run_chain",
    "sample_payload",
    "train_line",
]

LAST_LINE = "ranking only: no case was closed or cleared by the model"
ACTOR = "cli"  # the actor of every automated step started from the command line
NOTE = "note metrics cover alerted cases only; below-the-line sample: run `aml cases btl`"
POPULATION = "alerted cases only; below-the-line sample: run `aml cases btl` (Phase 7b)"
BTL_LAST_LINE = (
    "below-the-line sample is measurement only: no customer was alerted, closed or cleared"
)


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


def btl_line(s: BtlSample) -> str:
    """The sample as one line (``ci95`` is the 95 % Wilson interval of the suspicious share)."""
    low, high = ("-" if v is None else v for v in s.prevalence_ci95)
    return (
        f"btl sample_id={s.sample_id} run_id={s.run_id} population={s.population} size={s.size} "
        f"suspicious={s.suspicious} not_suspicious={s.not_suspicious} "
        f"estimated_missed={s.estimated_missed} ci95={low}-{high} reused={s.reused}"
    )


def btl_eval_line(e: BtlEvaluation) -> str:
    m = e.metrics
    return (
        f"btl-eval model={e.version} n={m['n']} n_suspicious={m['n_suspicious']} "
        f"roc_auc={_f(m.get('roc_auc'))} pr_auc={_f(m.get('pr_auc'))} "
        f"prevalence={_f(m.get('prevalence'))}"
    )


def sample_payload(s: BtlSample) -> dict[str, Any]:
    """The sample as JSON-safe data (the members included)."""
    return {
        "sample_id": s.sample_id, "run_id": s.run_id, "as_of": s.as_of.isoformat(),
        "seed": s.seed, "requested": s.requested, "population": s.population, "size": s.size,
        "suspicious": s.suspicious, "not_suspicious": s.not_suspicious,
        "estimated_missed": s.estimated_missed, "prevalence_ci95": list(s.prevalence_ci95),
        "reused": s.reused,
        "members": [
            {
                "golden_customer_id": m.golden_customer_id,
                "label": m.label,
                "typologies": list(m.typologies),
                "reason": m.reason,
            }
            for m in s.members
        ],
    }  # fmt: skip


def btl_evaluation(
    db: Database, settings: Settings, emit: Callable[[str], None]
) -> BtlEvaluation | None:
    """Measure the active model on the sample and print the line; None when there is no model."""
    try:
        evaluation = evaluate_btl(db, settings, actor=ACTOR)
    except PrioritizationError as exc:
        if str(exc) != NO_MODEL:
            raise
        emit(f"btl-eval skipped: {NO_MODEL}")
        return None
    emit(btl_eval_line(evaluation))
    return evaluation


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


def evaluation_payload(e: BtlEvaluation) -> dict[str, Any]:
    return {
        "eval_id": e.eval_id, "sample_id": e.sample_id, "model_id": e.model_id,
        "version": e.version, "metrics": e.metrics,
    }  # fmt: skip


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
    below = settings.cases.prioritization.below_the_line.enabled
    sample = None
    if below:  # the sample is drawn (and shown) before the model that is trained on it
        sample = draw_sample(db, settings, actor=ACTOR)
        emit(btl_line(sample))
        trained = train_with_btl(db, settings, actor=ACTOR).training
    else:
        trained = train(db, settings, actor=ACTOR)
    emit(f"model {train_line(trained)}")
    scored = score(db, settings, actor=ACTOR)
    emit(
        f"scored cases={scored.cases} queue={scored.queue} model={scored.version} "
        f"score_run_id={scored.score_run_id}"
    )
    h = scored.holdout
    emit(f"holdout n={h.get('n', 0)} {_metrics(h)} population=alerted-cases-only")
    evaluation = btl_evaluation(db, settings, emit) if sample is not None else None
    for line in _queue_lines(db, top):
        emit(line)
    emit(NOTE)
    emit(LAST_LINE)
    payload = eval_payload(trained, scored, settings)
    if sample is not None:
        payload["below_the_line"] = {
            "sample": sample_payload(sample),
            "evaluation": None if evaluation is None else evaluation_payload(evaluation),
        }
    return payload
