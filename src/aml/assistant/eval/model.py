"""Types of the assistant evaluation: golden questions, recorded answers, scores, metrics.

Everything here is plain data. The golden set says what a right answer contains (ids, VND
amounts, a typology code); an ``EvalAnswer`` is what the assistant returned for one question in
one retrieval mode; an ``ItemScore`` is the deterministic verdict on that answer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aml.common.config import RAG_EVAL_MODES, RAG_EVAL_TYPES

GOLDEN_SCHEMA = "golden/v1"
EVAL_SCHEMA = "rag-eval/v1"
TYPES = RAG_EVAL_TYPES  # ("fact", "multi_hop", "typology", "unanswerable", "injection")
MODES = RAG_EVAL_MODES  # ("graphrag", "vector"); the report follows the order of the config
ANSWERABLE_TYPES = ("fact", "multi_hop", "typology", "injection")
STATUS_OK = "ok"
STATUS_ERROR = "error"


class GoldenError(RuntimeError):
    """The golden set cannot be built from this database (or does not belong to it)."""


class EvalError(RuntimeError):
    """The evaluation cannot run or its result cannot be read."""


@dataclass(frozen=True)
class GoldenItem:
    id: str  # G-F01, G-M01, G-T01, G-U01, G-I01 ...
    type: str  # one of TYPES
    template: str
    language: str  # "vi" | "en"
    question: str
    case_id: str | None
    scenario_id: str | None
    expected_ids: tuple[str, ...]  # ids the answer must contain (sorted)
    expected_values: tuple[int, ...]  # VND amounts the answer must contain
    expected_typology: str | None  # typology code of ground_truth
    evidence_ids: tuple[str, ...]  # ids that count as a supported citation (sorted)
    expect_refusal: bool
    injection_phrase: str | None


@dataclass(frozen=True)
class GoldenSet:
    meta: dict[str, Any]  # schema, seed, dataset, counts, fingerprint
    items: tuple[GoldenItem, ...]


@dataclass(frozen=True)
class RunKey:
    """What an answer depends on besides the question; a stored answer is reused only on a match."""

    llm_model: str
    embed_model: str
    prompt_version: str


@dataclass(frozen=True)
class EvalAnswer:
    text: str
    citations: tuple[str, ...]
    flagged: tuple[str, ...]  # sentences the answer check of the assistant flagged
    refused: bool  # the refusal flag set by the assistant itself
    context_ids: tuple[str, ...]  # bare ids of every context item given to the LLM
    context_text: str  # the transaction memos of the context, one per line
    seconds: float = 0.0
    chat_calls: int = 0
    embed_calls: int = 0
    status: str = STATUS_OK  # "ok" | "error"
    error: str | None = None


AnswerFn = Callable[[GoldenItem, str], EvalAnswer]  # (item, mode)


@dataclass(frozen=True)
class Ratio:
    num: int
    den: int

    @property
    def value(self) -> float | None:
        """None when there is nothing to divide by: the metric has no value, it is not 0."""
        return None if self.den == 0 else self.num / self.den


@dataclass(frozen=True)
class ItemScore:
    item_id: str
    mode: str
    type: str
    status: str
    refused: bool  # read from the text, not from the flag of the assistant
    refusal_flag_agrees: bool
    refusal_ok: bool
    correct: bool | None  # None for a question that expects a refusal
    cited: int
    cited_supported: int
    flagged: int
    unknown_ids: tuple[str, ...]
    hallucinated: bool | None  # None when refused or failed
    exposed: bool | None  # None unless it is an injection question
    markers: tuple[str, ...]
    echoed: bool | None
    resisted: bool | None
    # Copied from the question and the answer so that eval_items.csv needs no other file.
    template: str = ""
    language: str = ""
    seconds: float = 0.0


@dataclass(frozen=True)
class ModeMetrics:
    answer_correctness: Ratio
    citation_precision: Ratio
    hallucination_rate: Ratio
    refusal_correctness: Ratio
    injection_resistance: Ratio
    injection_exposed: Ratio
    unanswerable_refused: Ratio
    answerable_refused: Ratio
    uncited_answers: int
    errors: int
    by_type: dict[str, Ratio]  # "answered as expected" per question type


@dataclass(frozen=True)
class EvalResult:
    meta: dict[str, Any]  # JSON types only, so a file reads back unchanged
    scores: list[ItemScore]
    metrics: dict[str, ModeMetrics]  # by mode
