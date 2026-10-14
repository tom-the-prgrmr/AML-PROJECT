"""`aml memo eval`: measure rules + model on a small gold set of hand-labelled memos.

The gold set is synthetic and labelled by the project team, not by investigators: it is enough to
see mistakes and to compare two prompts, not to claim an accuracy on real data. The measurement
stores no label and applies no threshold; it never reads the labels people have corrected, so it
keeps measuring what the rule layer and the model do on their own.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aml.common.audit import audit
from aml.common.config import PROJECT_ROOT, Settings
from aml.common.db import Database
from aml.memo.classify import (
    CATEGORIES,
    FALLBACK,
    FEW_SHOT,
    LLM,
    RULE,
    Classification,
    MemoError,
    classify_one,
)
from aml.memo.normalize import MEMO_VERSION, injection_pattern, normalize_memo
from aml.memo.store import MODULE

if TYPE_CHECKING:
    from aml.assistant.llm import LLMClient

HEADER = ["memo", "category", "source"]
SOURCES = ("generator", "handwritten")


@dataclass(frozen=True)
class GoldRow:
    memo: str  # verbatim, as in the file
    category: str
    source: str  # generator | handwritten


def read_gold(path: Path, max_chars: int = 200) -> list[GoldRow]:
    """Read and check a gold file (UTF-8 CSV with the header ``memo,category,source``).

    Row numbers in the errors count from 1 and leave the header out.
    """
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as handle:
            lines = list(csv.reader(handle))
    except OSError as exc:
        raise MemoError(f"cannot read the gold file {path}: {exc}") from exc
    if not lines or lines[0] != HEADER:
        raise MemoError(f"gold file {path} must start with the header {','.join(HEADER)}")
    few_shot = {memo for memo, _ in FEW_SHOT}
    seen: set[str] = set()
    rows: list[GoldRow] = []
    for n, line in enumerate(lines[1:], start=1):
        if len(line) != len(HEADER):
            raise MemoError(f"gold row {n} must have {len(HEADER)} columns")
        memo, category, source = line
        if category not in CATEGORIES:
            raise MemoError(f"unknown category '{category}' in gold row {n}")
        if source not in SOURCES:
            raise MemoError(f"unknown source '{source}' in gold row {n}")
        key = normalize_memo(memo, max_chars)
        if not key:
            raise MemoError(f"empty memo in gold row {n}")
        if key in seen:
            raise MemoError(f"duplicate gold memo in row {n}")
        if key in few_shot:
            raise MemoError(f"gold row {n} is also a few-shot example")
        seen.add(key)
        rows.append(GoldRow(memo, category, source))
    return rows


def _shown(path: Path) -> str:
    """The path as written into results: relative to the project when it lies inside it."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 4)


def evaluate_gold(
    rows: Sequence[GoldRow], predicted: Sequence[Classification], *, model: str | None = None
) -> dict[str, Any]:
    """Accuracy, per-category precision and recall, and the confusion of gold vs predicted. Pure.

    Ratios are rounded to 4 and are None when the denominator is 0; ``confusion`` only holds the
    cells that are not 0; ``errors`` are in file order.
    """
    pairs = list(zip(rows, predicted, strict=True))
    hit = [gold.category == got.category for gold, got in pairs]
    by_category = {}
    for name in CATEGORIES:
        n = sum(gold.category == name for gold, _ in pairs)
        guessed = sum(got.category == name for _, got in pairs)
        correct = sum(
            ok and gold.category == name for ok, (gold, _) in zip(hit, pairs, strict=True)
        )
        by_category[name] = {
            "n": n,
            "correct": correct,
            "predicted": guessed,
            "precision": _ratio(correct, guessed),
            "recall": _ratio(correct, n),
        }
    by_source = {}
    for source in SOURCES:
        flags = [ok for ok, (gold, _) in zip(hit, pairs, strict=True) if gold.source == source]
        by_source[source] = {
            "n": len(flags),
            "correct": sum(flags),
            "accuracy": _ratio(sum(flags), len(flags)),
        }
    confusion: dict[str, dict[str, int]] = {}
    for gold, got in pairs:
        row = confusion.setdefault(gold.category, {})
        row[got.category] = row.get(got.category, 0) + 1
    return {
        "version": MEMO_VERSION,
        "model": model,
        "n": len(pairs),
        "correct": sum(hit),
        "accuracy": _ratio(sum(hit), len(pairs)),
        "by_category": by_category,
        "by_source": by_source,
        "by_method": {m: sum(got.method == m for _, got in pairs) for m in (RULE, LLM, FALLBACK)},
        "confusion": confusion,
        "errors": [
            {
                "memo": gold.memo,
                "expected": gold.category,
                "predicted": got.category,
                "method": got.method,
            }
            for ok, (gold, got) in zip(hit, pairs, strict=True)
            if not ok
        ],
    }


def run_memo_eval(
    db: Database,
    settings: Settings,
    llm: LLMClient | None,
    *,
    gold_path: Path | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Classify every gold memo the way a real run does (rules first) and measure the result.

    Writes one audit row and nothing else: no label, no run, no feature. There is no pass mark.
    """
    model = settings.ollama.llm_model
    path = Path(gold_path) if gold_path is not None else settings.path(settings.memo.gold_path)
    rows = read_gold(path, settings.memo.max_chars)
    norms = [normalize_memo(row.memo, settings.memo.max_chars) for row in rows]
    need_llm = sum(injection_pattern(norm) == 0 for norm in norms)
    if llm is None and need_llm:
        raise MemoError(f"{need_llm} gold memo(s) need the LLM but it is not available")
    client_model = getattr(llm, "chat_model", model) if llm is not None else model
    if client_model != model:  # a fake client must not be reported under the real model's name
        raise MemoError(
            f"llm client model '{client_model}' differs from ollama.llm_model '{model}'"
        )
    predicted: list[Classification] = []
    for norm in norms:
        try:
            label = classify_one(norm, llm, model=model, max_retries=settings.memo.max_retries)
        except Exception as exc:
            raise MemoError(
                f"llm call failed after {len(predicted)} of {len(norms)} gold memo(s): "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        predicted.append(label)
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    result = evaluate_gold(rows, predicted, model=model)
    result["gold"] = {"path": _shown(path), "sha256": sha256, "rows": len(rows)}
    audit(
        db,
        module=MODULE,
        entity_type="memo_eval",
        entity_id=sha256[:16],
        decision="MEMO_EVAL_COMPLETED",
        reason=(
            f"evaluated {MEMO_VERSION} with {model} on {result['n']} gold memo(s): "
            f"{result['correct']} correct (accuracy {result['accuracy']}); "
            "measurement only, no label stored"
        ),
        version=MEMO_VERSION,
        actor=actor or settings.audit.system_actor,
        details={
            key: result[key]
            for key in ("gold", "n", "correct", "accuracy", "by_category", "by_source", "by_method")
        },
    )
    return result
