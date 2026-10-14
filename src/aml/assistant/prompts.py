"""Prompts and JSON schemas of the answering layer (pure).

The system message is a constant per (prompt version, language, task): no character of the data or
of the question ever reaches it. The user message is ``Evidence:`` + 8b's `render_evidence` +
``Question:`` + the question. Wrapping untrusted text is 8b's job alone; this module adds no second
mechanism and never puts ``Evidence.data`` in a prompt.

The schema binds every ``cites`` entry to the refs of this turn (``E1``..``En``) with an ``enum``:
measured on the 3B model, a free-text ``cites`` made it copy the ``cite:`` line instead of a handle.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from aml.assistant.evidence import UNTRUSTED_NOTICE, Evidence, render_evidence
from aml.assistant.llm import ChatMessage

ANSWER_PROMPT_VERSION = "answer/v1"
NARRATIVE_PROMPT_VERSION = "narrative/v1"
TASKS = ("answer", "narrative")
SECTION_KEYS = ("subject", "timeline", "typologies", "red_flags", "next_step")
RETRY_MESSAGE = (
    "Your previous reply was not valid JSON in the required format. Reply again with only the "
    "JSON object, nothing else."
)
_LANGUAGE_LINE = {"vi": "Answer in Vietnamese.", "en": "Answer in English."}

_COMMON = f"""You help an anti-money-laundering investigator. You only read evidence and write \
text; you never decide a case.

{UNTRUSTED_NOTICE}

Rules:
1. Use only the evidence items of the user message. Each item starts with a handle in brackets, \
such as [E1].
2. Every sentence cites at least one handle in "cites", for example ["E1"]. Cite only the items \
that state what the sentence says.
3. Copy amounts and dates exactly as the evidence writes them: amounts like 390,000,000 VND, \
dates as YYYY-MM-DD.
4. Never say that a customer, an account, a transaction or a case is clean, safe or legitimate, \
and never recommend to close, clear, approve or not report anything. A human investigator \
decides."""

_TASK = {
    "answer": """5. If the evidence does not answer the question, reply with status \
"insufficient_evidence" and no sentences.

Reply with JSON only: {"status": "answered" or "insufficient_evidence", "sentences": \
[{"text": "...", "cites": ["E1"]}]}""",
    "narrative": """5. Write a draft case narrative for the investigator. "subject": who the \
customer is; "timeline": what happened, in date order; "typologies": which typologies the \
activity matches; "red_flags": what looks unusual; "next_step": what the investigator could \
check next, never a decision. Leave a list empty when the evidence says nothing about it; that \
is the same as insufficient_evidence for that part.

Reply with JSON only: {"subject": [{"text": "...", "cites": ["E1"]}], "timeline": [...], \
"typologies": [...], "red_flags": [...], "next_step": [...]}""",
}


def _sentences(refs: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "cites": {"type": "array", "minItems": 1, "items": {"enum": list(refs)}},
            },
            "required": ["text", "cites"],
        },
    }


def answer_schema(refs: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["answered", "insufficient_evidence"]},
            "sentences": _sentences(refs),
        },
        "required": ["status", "sentences"],
    }


def narrative_schema(refs: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {key: _sentences(refs) for key in SECTION_KEYS},
        "required": list(SECTION_KEYS),
    }


def system_message(*, language: str, task: str = "answer") -> str:
    if language not in _LANGUAGE_LINE:
        raise ValueError(f"language '{language}' is not available; choose vi or en")
    if task not in TASKS:
        raise ValueError(f"unknown prompt task {task!r}")
    return f"{_COMMON}\n{_TASK[task]}\n\n{_LANGUAGE_LINE[language]}"


def build_messages(
    question: str, evidence: Sequence[Evidence], *, language: str, task: str = "answer"
) -> list[ChatMessage]:
    """Exactly two messages: the constant system message, then the evidence and the question."""
    user = "Evidence:\n" + render_evidence(evidence) + "\n\nQuestion:\n" + question
    return [
        {"role": "system", "content": system_message(language=language, task=task)},
        {"role": "user", "content": user},
    ]
