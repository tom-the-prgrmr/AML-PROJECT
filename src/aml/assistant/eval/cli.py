"""Bodies of ``aml rag eval``: produce the output lines; ``aml/cli.py`` only prints them.

Three ways to run: ``--golden-only`` (build and write the golden set; needs the database only),
``--report-only`` (rebuild the report from ``eval_result.json``; needs nothing), and the full run.
Only the full run needs the assistant itself, and it reaches it through ``load_adapter`` alone.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from aml.assistant.eval.golden import (
    GOLDEN_FILE,
    build_golden,
    dataset_counts,
    read_golden,
    write_golden,
)
from aml.assistant.eval.model import TYPES, EvalError, GoldenError, GoldenSet, ModeMetrics, Ratio
from aml.assistant.eval.report import (
    ITEMS_FILE,
    REPORT_FILE,
    RESULT_FILE,
    side_effects_line,
    write_report,
)
from aml.assistant.eval.runner import check_modes, check_types, pending, run_eval
from aml.assistant.eval.store import ANSWERS_FILE
from aml.common.config import Settings
from aml.common.db import Database, get_db
from aml.common.services import neo4j_status, ollama_status

ADAPTER = "aml.assistant.eval.adapter"
EVAL_ACTOR = "eval"  # actor of the retrieval / answering audit rows written during a run


def results_dir(settings: Settings) -> Path:
    return settings.path(settings.rag_eval.results_dir)


def check_arguments(types: Sequence[str], modes: Sequence[str]) -> None:
    """Raise ``EvalError`` for an unknown ``--type`` or ``--mode`` (a usage error: exit 2)."""
    check_types(types)
    check_modes(modes)


# ---------------------------------------------------------------------------------- golden set
def _golden_line(golden: GoldenSet) -> str:
    counts = " ".join(f"{kind}={golden.meta['counts'][kind]}" for kind in TYPES)
    return f"golden items={len(golden.items)} {counts} fingerprint={golden.meta['fingerprint']}"


def golden_lines(settings: Settings) -> list[str]:
    """``--golden-only``: build the golden set from the database and write it."""
    with get_db(settings) as db:
        golden = build_golden(db, settings)
    path = write_golden(golden, results_dir(settings))
    return [_golden_line(golden), f"wrote {path}"]


def _golden_for_run(db: Database, settings: Settings, lines: list[str]) -> GoldenSet:
    """The stored golden set (built and written first when there is none), checked against the
    database: questions generated from other data would be scored against the wrong answers."""
    directory = results_dir(settings)
    if not (directory / GOLDEN_FILE).exists():
        golden = build_golden(db, settings)
        lines += [_golden_line(golden), f"wrote {write_golden(golden, directory)}"]
        return golden
    golden = read_golden(directory)
    built_on = (golden.meta.get("seed"), golden.meta.get("dataset"))
    if built_on != (settings.seed, dataset_counts(db)):
        raise GoldenError(
            f"golden set was built for another dataset (seed {built_on[0]}, {built_on[1]}): "
            "rebuild it with aml rag eval --golden-only"
        )
    return golden


# ---------------------------------------------------------------------------------- report
def report_lines(settings: Settings) -> list[str]:
    """``--report-only``: rebuild the report and the item table from the result file."""
    report, items = write_report(results_dir(settings))
    return [f"wrote {report}", f"wrote {items}"]


# ---------------------------------------------------------------------------------- full run
def load_adapter() -> Any:
    """THE ONLY PLACE where the evaluation reaches retrieval and answering (Phase 8b / 8c).

    The adapter module must provide ``run_key(settings)``, ``build_answer_fn(db, settings, *,
    llm=None, actor=None)`` and ``knowledge_support(settings)``. It is imported here, after the
    arguments and the golden set have been checked, so that everything else works without it.
    """
    try:
        return importlib.import_module(ADAPTER)
    except ModuleNotFoundError as exc:
        if exc.name != ADAPTER:
            raise  # the adapter exists and one of its own imports is missing: a real error
        raise EvalError(
            f"the evaluation adapter ({ADAPTER}) does not exist yet: it needs the answering step "
            "of Phase 8c. Until then only --golden-only and --report-only work"
        ) from exc


def _require_services(settings: Settings) -> None:
    """Questions are still to be asked: Neo4j and (unless the provider is fake) Ollama must run."""
    neo = neo4j_status(settings)
    if not neo.up:
        raise EvalError(f"neo4j not available: {neo.detail}")
    if settings.assistant.provider != "fake":
        llm = ollama_status(settings)
        if not llm.up:
            raise EvalError(f"ollama not available: {llm.detail}")


def _short(ratio: Ratio) -> str:
    return f"{ratio.num}/{ratio.den}"


def _mode_line(mode: str, m: ModeMetrics) -> str:
    return (
        f"mode={mode} correctness={_short(m.answer_correctness)} "
        f"citation_precision={_short(m.citation_precision)} "
        f"hallucination={_short(m.hallucination_rate)} refusal={_short(m.refusal_correctness)} "
        f"injection={_short(m.injection_resistance)} exposed={_short(m.injection_exposed)}"
    )


def eval_lines(
    settings: Settings,
    *,
    limit: int | None,
    types: Sequence[str],
    modes: Sequence[str],
    force: bool,
    command: str,
    actor: str,
) -> tuple[list[str], list[str]]:
    """The full run; returns (stdout lines, stderr lines). Stderr lines mean exit code 1."""
    directory = results_dir(settings)
    run_modes = list(modes) or list(settings.rag_eval.modes)
    out: list[str] = []
    with get_db(settings) as db:
        golden = _golden_for_run(db, settings, out)
        adapter = load_adapter()
        key = adapter.run_key(settings)
        selection = {"modes": run_modes, "types": list(types) or None, "limit": limit}
        if pending(golden, directory / ANSWERS_FILE, key, force=force, **selection):
            _require_services(settings)  # before anything is asked or written
        result = run_eval(
            db,
            settings,
            golden,
            answer_fn=adapter.build_answer_fn(db, settings, actor=EVAL_ACTOR),
            key=key,
            results_dir=directory,
            force=force,
            knowledge_support=adapter.knowledge_support(settings),
            command=command,
            actor=actor,
            **selection,
        )
    meta = result.meta
    out.append(
        f"eval items={meta['items_answered']}/{meta['items_total']} modes={','.join(run_modes)} "
        f"asked={meta['asked']} reused={meta['reused']} errors={meta['errors']} "
        f"seconds={meta['total_seconds']}"
    )
    out += [_mode_line(mode, result.metrics[mode]) for mode in run_modes]
    written = (ANSWERS_FILE,) if meta["asked"] else ()  # untouched when every answer was reused
    out += [
        f"wrote {directory / name}" for name in (*written, RESULT_FILE, REPORT_FILE, ITEMS_FILE)
    ]
    err = [side_effects_line(meta["side_effects"])] if meta["side_effects"] else []
    return out, err
