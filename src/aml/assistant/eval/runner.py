"""Run the evaluation: ask every golden question in every mode, score the answers, write files.

The function that answers a question is a parameter (``answer_fn``), so this module knows nothing
about retrieval or language models and can be tested with scripted answers. Answers go to the
answer store one by one; a stored answer with the same key is reused instead of asked again.
The run reads the database, writes one ``EVALUATED`` audit row and nothing else: the row counts
of the decision tables are compared before and after, and any change is reported.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from aml.assistant.eval import queries
from aml.assistant.eval.metrics import aggregate, score_item
from aml.assistant.eval.model import (
    EVAL_SCHEMA,
    MODES,
    STATUS_ERROR,
    STATUS_OK,
    TYPES,
    AnswerFn,
    EvalAnswer,
    EvalError,
    EvalResult,
    GoldenItem,
    GoldenSet,
    RunKey,
)
from aml.assistant.eval.report import write_report, write_result
from aml.assistant.eval.store import ANSWERS_FILE, append_answer, load_answers
from aml.assistant.eval.text import extract_ids
from aml.common.audit import audit
from aml.common.config import PROJECT_ROOT, Settings
from aml.common.db import Database

AUDIT_MODULE = "assistant"


# ---------------------------------------------------------------------------------- selection
def check_modes(modes: Sequence[str]) -> None:
    for mode in modes:
        if mode not in MODES:
            raise EvalError(f"unknown mode {mode!r}: choose from {', '.join(MODES)}")
    if len(set(modes)) != len(modes):
        raise EvalError("modes must not repeat")


def check_types(types: Sequence[str]) -> None:
    for kind in types:
        if kind not in TYPES:
            raise EvalError(f"unknown question type {kind!r}: choose from {', '.join(TYPES)}")


def select_items(
    golden: GoldenSet, types: Sequence[str] | None, limit: int | None
) -> list[GoldenItem]:
    """Filter by type, then keep the first ``limit`` questions in golden-set order."""
    check_types(types or ())
    if limit is not None and limit < 1:
        raise EvalError("limit must be >= 1")
    items = [i for i in golden.items if not types or i.type in types]
    return items if limit is None else items[:limit]


def pending(
    golden: GoldenSet,
    path: Path,
    key: RunKey,
    *,
    modes: Sequence[str],
    types: Sequence[str] | None = None,
    limit: int | None = None,
    force: bool = False,
) -> list[tuple[str, str]]:
    """The (question, mode) pairs a run would have to ask: no usable answer is stored for them."""
    check_modes(modes)
    stored = {} if force else load_answers(path, golden.meta["fingerprint"], key)
    return [
        (item.id, mode)
        for item in select_items(golden, types, limit)
        for mode in modes
        if (item.id, mode) not in stored or stored[(item.id, mode)].status != STATUS_OK
    ]


def load_known_ids(db: Database, candidates: Collection[str]) -> set[str]:
    """The candidates that exist in the database (transaction, account, customer, case ids)."""
    return queries.existing_ids(db, candidates)


# ---------------------------------------------------------------------------------- one question
def _ask(answer_fn: AnswerFn, item: GoldenItem, mode: str) -> EvalAnswer:
    """Call ``answer_fn``; an exception becomes an ``error`` record and the run goes on.

    ``KeyboardInterrupt`` is not caught: the run stops and keeps the answers stored so far.
    """
    clock = time.perf_counter()
    try:
        answer = answer_fn(item, mode)
    except Exception as exc:
        return EvalAnswer(
            text="",
            citations=(),
            flagged=(),
            refused=False,
            context_ids=(),
            context_text="",
            seconds=round(time.perf_counter() - clock, 3),
            status=STATUS_ERROR,
            error=f"{type(exc).__name__}: {exc}",
        )
    if answer.seconds == 0.0:  # the answer function did not time itself
        answer = replace(answer, seconds=round(time.perf_counter() - clock, 3))
    return answer


# ---------------------------------------------------------------------------------- meta
def _version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def _git_commit() -> str | None:
    """Short commit id, with ``-dirty`` when tracked files differ from it (not reproducible)."""
    commit = _git("rev-parse", "--short", "HEAD")
    if not commit:
        return None
    return f"{commit}-dirty" if _git("status", "--porcelain", "--untracked-files=no") else commit


def _provenance(settings: Settings, golden: GoldenSet, key: RunKey, command: str) -> dict[str, Any]:
    return {
        "schema": EVAL_SCHEMA,
        "command": command,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "total_seconds": 0.0,  # set by run_eval once the answers are in
        "git_commit": _git_commit(),
        "versions": {"python": platform.python_version(), "aml": _version("aml-toolkit")},
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "seed": settings.seed,
        "llm_model": key.llm_model,
        "embed_model": key.embed_model,
        "prompt_version": key.prompt_version,
        "golden": {name: golden.meta[name] for name in ("schema", "fingerprint", "counts")},
        "dataset": golden.meta["dataset"],
    }


# ---------------------------------------------------------------------------------- the run
def run_eval(
    db: Database,
    settings: Settings,
    golden: GoldenSet,
    *,
    answer_fn: AnswerFn,
    key: RunKey,
    results_dir: Path,
    modes: Sequence[str] | None = None,  # None -> settings.rag_eval.modes
    limit: int | None = None,
    types: Sequence[str] | None = None,
    force: bool = False,
    knowledge_support: Callable[[str], Collection[str]] | None = None,
    command: str = "aml rag eval",
    actor: str | None = None,
) -> EvalResult:
    """Ask, score and report; return the result that was written to ``results_dir``."""
    run_modes = list(modes if modes is not None else settings.rag_eval.modes)
    check_modes(run_modes)
    items = select_items(golden, types, limit)
    fingerprint = golden.meta["fingerprint"]
    path = results_dir / ANSWERS_FILE
    meta = _provenance(settings, golden, key, command)
    clock = time.perf_counter()
    tables_before = queries.counts(db, "decision_tables")

    stored = {} if force else load_answers(path, fingerprint, key)
    answers: dict[tuple[str, str], EvalAnswer] = {}
    asked = 0
    for item in items:  # question outside, mode inside: a cut-short run still compares modes
        for mode in run_modes:
            answer = stored.get((item.id, mode))
            if answer is None or answer.status != STATUS_OK:  # failed answers are asked again
                answer = _ask(answer_fn, item, mode)
                append_answer(path, fingerprint, item.id, mode, key, answer)  # before the next one
                asked += 1
            answers[(item.id, mode)] = answer

    tables_after = queries.counts(db, "decision_tables")
    side_effects = {
        table: tables_after[table] - n
        for table, n in tables_before.items()
        if tables_after[table] != n
    }
    mentioned = {i for a in answers.values() for i in (*extract_ids(a.text), *a.citations)}
    known = load_known_ids(db, mentioned)
    scores = [
        score_item(
            item,
            answers[(item.id, mode)],
            mode,
            known_ids=known,
            knowledge_support=knowledge_support,
        )
        for item in items
        for mode in run_modes
    ]
    errors = sum(a.status != STATUS_OK for a in answers.values())
    meta |= {
        "total_seconds": round(time.perf_counter() - clock, 3),
        "modes": run_modes,
        "params": {"limit": limit, "types": list(types) if types else None, "force": force},
        "items_total": len(golden.items),
        "items_answered": len(items),
        "partial": len(items) < len(golden.items),
        "asked": asked,
        "reused": len(answers) - asked,
        "errors": errors,
        "llm_calls": {
            "chat": sum(a.chat_calls for a in answers.values()),
            "embed": sum(a.embed_calls for a in answers.values()),
        },
        "side_effects": side_effects,
    }
    audit(
        db,
        module=AUDIT_MODULE,
        entity_type="evaluation",
        entity_id=fingerprint,
        decision="EVALUATED",
        reason=(
            f"assistant evaluation on {len(items)} of {len(golden.items)} questions x "
            f"{len(run_modes)} modes: {asked} asked, {len(answers) - asked} reused, {errors} failed"
        ),
        version=EVAL_SCHEMA,
        actor=actor or settings.audit.system_actor,
        details={
            "modes": run_modes,
            "items": len(items),
            "asked": asked,
            "reused": len(answers) - asked,
            "errors": errors,
            "llm_model": key.llm_model,
            "embed_model": key.embed_model,
            "prompt_version": key.prompt_version,
        },
    )
    result = EvalResult(
        meta=meta,
        scores=scores,
        metrics={mode: aggregate([s for s in scores if s.mode == mode]) for mode in run_modes},
    )
    write_result(result, results_dir)
    write_report(results_dir)
    return result
