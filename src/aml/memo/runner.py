"""`aml memo classify`: label every memo key of `transactions` once, and never ask twice.

The model is not deterministic even at temperature 0, so the label of a key is the first answer
that was stored: a key with a RULE or LLM row is never asked again, and a key a person has
relabelled is never asked again either. Each LLM key is written with its audit row in its own
transaction, so a run that stops half way keeps what it did and the next run continues from there.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

import pandas as pd

from aml.cases.items import sql_statement
from aml.cases.values import lower_columns
from aml.common.audit import AuditEvent, audit_many
from aml.common.config import Settings
from aml.common.db import Database
from aml.memo.classify import LLM, RULE, Classification, MemoError, classify_one
from aml.memo.normalize import MEMO_VERSION, injection_pattern, memo_key, normalize_memo
from aml.memo.store import (
    MODULE,
    classification_event,
    insert_classifications,
    now,
    read_labels,
    scalar,
)

if TYPE_CHECKING:
    from aml.assistant.llm import LLMClient

__all__ = ["MemoError", "MemoPlan", "MemoRun", "classify_memos", "plan_memos", "read_categories"]


@dataclass(frozen=True)
class MemoPlan:
    transactions: int
    with_memo: int  # transactions whose memo is not empty after normalisation
    distinct_memos: int  # distinct raw memos
    keys: int  # keys after normalisation
    reused: int  # keys that already have a RULE / LLM label (or a person's) for this model
    rule_keys: int  # new keys the rule layer will label
    llm_keys: int  # new keys that need the LLM


@dataclass(frozen=True)
class MemoRun:
    run_id: int
    version: str  # MEMO_VERSION
    model: str  # settings.ollama.llm_model
    transactions: int
    with_memo: int
    distinct_memos: int
    keys: int
    reused: int
    by_rule: int
    by_llm: int
    fallback: int
    llm_calls: int
    left: int  # keys not classified when the run stopped early; 0 = complete
    seconds: float


class _Counting:
    """Passes chat calls through to a client and counts them, including the ones that raise."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.chat_model = inner.chat_model
        self.calls = 0

    def chat(self, messages: Any, *, json_schema: Any = None) -> str:
        self.calls += 1
        return self.inner.chat(messages, json_schema=json_schema)


@dataclass(frozen=True)
class _Work:
    """What a run has to do: the plan plus the new keys, as ``memo_norm -> transactions``."""

    plan: MemoPlan
    rule: dict[str, int]
    llm: dict[str, int]


def _work(db: Database, settings: Settings) -> _Work:
    """Read the distinct memos, normalise them in Python and split the keys (reads only)."""
    raw = lower_columns(db.query_df(sql_statement(db, "memo/distinct_memos.sql")))
    keys: dict[str, int] = {}
    with_memo = distinct = 0
    for memo, n in zip(raw["memo"], raw["transactions"], strict=True):
        norm = normalize_memo(memo, settings.memo.max_chars)
        if norm:
            keys[norm] = keys.get(norm, 0) + int(n)
            with_memo += int(n)
            distinct += 1
    labels = read_labels(db, settings)
    settled = labels["model_method"].isin([RULE, LLM]) | (labels["method"] == "HUMAN")
    done = set(labels.loc[settled, "memo_key"])  # a FALLBACK key is asked again
    new = {norm: n for norm, n in sorted(keys.items()) if memo_key(norm) not in done}
    rule = {norm: n for norm, n in new.items() if injection_pattern(norm)}
    llm = {norm: n for norm, n in new.items() if norm not in rule}
    plan = MemoPlan(
        transactions=int(raw["transactions"].sum()) if len(raw) else 0,
        with_memo=with_memo,
        distinct_memos=distinct,
        keys=len(keys),
        reused=len(keys) - len(new),
        rule_keys=len(rule),
        llm_keys=len(llm),
    )
    return _Work(plan, rule, llm)


def plan_memos(db: Database, settings: Settings) -> MemoPlan:
    """What a run would do, without writing anything or calling a model."""
    return _work(db, settings).plan


def read_categories(db: Database, settings: Settings) -> dict[str, str]:
    """``memo_key -> category`` in force (a person's label wins over the rule or the model)."""
    labels = read_labels(db, settings)
    return dict(zip(labels["memo_key"], labels["category"], strict=True))


def _run_event(run: MemoRun, actor: str) -> AuditEvent:
    new = run.by_rule + run.by_llm + run.fallback
    return AuditEvent(
        module=MODULE,
        entity_type="memo_run",
        entity_id=str(run.run_id),
        decision="MEMO_RUN_INCOMPLETE" if run.left else "MEMO_RUN_COMPLETED",
        reason=(
            f"classified {new} new memo key(s) of {run.keys} ({run.by_rule} by rule, "
            f"{run.by_llm} by {run.model}, {run.fallback} fallback), reused {run.reused}; "
            f"{run.llm_calls} LLM call(s) for {run.with_memo} transactions with a memo; "
            "features only, no alert"
        ),
        version=MEMO_VERSION,
        actor=actor,
        details=asdict(run),
    )


def _store_run(db: Database, run: MemoRun, actor: str) -> None:
    """The run row and its audit row, in one transaction."""
    row = {
        "run_id": run.run_id, "run_ts": now(), "memo_version": run.version,
        "llm_model": run.model, "transactions": run.transactions, "with_memo": run.with_memo,
        "distinct_memos": run.distinct_memos, "memo_keys": run.keys, "reused": run.reused,
        "by_rule": run.by_rule, "by_llm": run.by_llm, "fallback": run.fallback,
        "llm_calls": run.llm_calls, "keys_left": run.left, "seconds": run.seconds, "actor": actor,
    }  # fmt: skip
    with db.transaction():
        db.insert_df("memo_runs", pd.DataFrame([row]))
        audit_many(db, [_run_event(run, actor)])


def classify_memos(
    db: Database, settings: Settings, llm: LLMClient | None, *, actor: str | None = None
) -> MemoRun:
    """Classify every memo key that has no label yet and store the run.

    Raises `MemoError` before anything is written when the client is for another model or more
    keys need the LLM than ``memo.max_llm_keys``. When the LLM is missing or a call fails, the keys
    done so far and a run row with ``left > 0`` are stored first, then `MemoError` is raised.
    """
    model = settings.ollama.llm_model
    actor = actor or settings.audit.system_actor
    client_model = getattr(llm, "chat_model", model) if llm is not None else model
    if client_model != model:  # labels of a fake client must never be stored as the real model's
        raise MemoError(
            f"llm client model '{client_model}' differs from ollama.llm_model '{model}'"
        )
    started = time.perf_counter()
    work = _work(db, settings)
    plan = work.plan
    if plan.llm_keys > settings.memo.max_llm_keys:
        raise MemoError(
            f"{plan.llm_keys} memo keys need the LLM, more than "
            f"memo.max_llm_keys={settings.memo.max_llm_keys}"
        )
    # A run that was killed may have stored classifications but no run row: never reuse its id.
    run_id = 1 + max(
        scalar(db, f"SELECT COALESCE(MAX(run_id), 0) FROM {table}")
        for table in ("memo_runs", "memo_classifications")
    )
    retries = settings.memo.max_retries

    def store(labelled: list[tuple[Classification, int]]) -> None:
        """Some keys and their audit rows, in one transaction."""
        events = [
            classification_event(c, run_id=run_id, model=model, transactions=n, actor=actor)
            for c, n in labelled
        ]
        with db.transaction():
            insert_classifications(db, run_id=run_id, model=model, rows=labelled)
            audit_many(db, events)

    if work.rule:  # the rule keys never reach a model
        store([(classify_one(norm, None, model=model), n) for norm, n in work.rule.items()])
    todo = list(work.llm.items())  # ascending memo_norm
    done: list[Classification] = []
    failure: str | None = None
    counted = _Counting(llm) if llm is not None else None
    interrupted: BaseException | None = None
    if counted is None and todo:
        failure = f"{len(todo)} memo key(s) need the LLM but it is not available"
    else:
        try:
            for norm, n in todo:
                try:
                    label = classify_one(norm, counted, model=model, max_retries=retries)
                except Exception as exc:  # no connection, missing model, ...: stop, never guess
                    failure = (
                        f"llm call failed after {len(done)} of {len(todo)} memo key(s): "
                        f"{type(exc).__name__}: {exc}"
                    )
                    break
                store([(label, n)])  # one key, one transaction: a stop loses nothing
                done.append(label)
        except BaseException as exc:  # Ctrl-C: record what was left, then stop as asked
            interrupted = exc
    by_llm = sum(c.method == LLM for c in done)
    run = MemoRun(
        run_id=run_id,
        version=MEMO_VERSION,
        model=model,
        transactions=plan.transactions,
        with_memo=plan.with_memo,
        distinct_memos=plan.distinct_memos,
        keys=plan.keys,
        reused=plan.reused,
        by_rule=plan.rule_keys,
        by_llm=by_llm,
        fallback=len(done) - by_llm,
        llm_calls=counted.calls if counted is not None else 0,  # failed calls included
        left=len(todo) - len(done),
        seconds=round(time.perf_counter() - started, 3),
    )
    _store_run(db, run, actor)
    if interrupted is not None:
        raise interrupted
    if failure:
        raise MemoError(failure)
    return run
