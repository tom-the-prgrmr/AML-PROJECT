"""The answer store: ``eval_answers.jsonl``, one JSON line per (question, mode) that was asked.

Answers are appended as soon as they arrive, so an interrupted run keeps what it has and the next
run asks only what is missing. A stored answer belongs to one golden set (its fingerprint) and
one ``RunKey`` (chat model, embedding model, prompt version); for the same key the later line
replaces the earlier one. A line that cannot be read (a write cut short) is passed over.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aml.assistant.eval.model import EvalAnswer, RunKey

ANSWERS_FILE = "eval_answers.jsonl"
_TUPLES = ("citations", "flagged", "context_ids")


def append_answer(
    path: Path, golden: str, item_id: str, mode: str, key: RunKey, answer: EvalAnswer
) -> None:
    """Append one line and flush it to disk before returning."""
    record = {"golden": golden, "item_id": item_id, "mode": mode, **asdict(key), **asdict(answer)}
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("ab") as handle:
        # A previous write that was cut short leaves no line end: start on a fresh line.
        handle.write((("\n" if _is_torn(path) else "") + line).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def _is_torn(path: Path) -> bool:
    """True when the file does not end with a line end."""
    if path.stat().st_size == 0:
        return False
    with path.open("rb") as handle:
        handle.seek(-1, 2)
        return handle.read(1) != b"\n"


def _answer(raw: dict[str, Any]) -> EvalAnswer:
    fields = {name: raw[name] for name in EvalAnswer.__dataclass_fields__ if name in raw}
    return EvalAnswer(**{**fields, **{name: tuple(fields[name]) for name in _TUPLES}})


def load_answers(path: Path, golden: str, key: RunKey) -> dict[tuple[str, str], EvalAnswer]:
    """(item_id, mode) -> the latest stored answer of this golden set and this key."""
    answers: dict[tuple[str, str], EvalAnswer] = {}
    if not path.exists():
        return answers
    wanted = {"golden": golden, **asdict(key)}
    # Split on b"\n" only: str.splitlines() would also cut a line at U+2028 or U+0085 inside an
    # answer, and a write cut short inside a multi-byte character must not fail the whole file.
    for line in path.read_bytes().split(b"\n"):
        try:
            raw = json.loads(line.decode("utf-8"))
            if all(raw.get(name) == value for name, value in wanted.items()):
                answers[(raw["item_id"], raw["mode"])] = _answer(raw)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue  # a torn or foreign line: not an answer
    return answers
