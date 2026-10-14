"""`answer_question()`: a cited answer to an investigator's question, checked before it is shown.

    question -> retrieve (8b) -> prompt -> local model (JSON) -> parse -> post-check -> Answer

The model only returns JSON and may cite only the handles (``E1``..``En``) of the evidence it was
given. Every sentence is checked (`validation.check_claims`); a sentence that fails is shown with an
``[UNVERIFIED]`` prefix, and when no sentence passes the answer becomes a refusal. The assistant
reads and drafts only: it never clears, closes, files or records a decision on a case.

One audit row per question (``ANSWERED`` / ``INSUFFICIENT_EVIDENCE`` / ``FAILED``). 8b writes its
own ``RETRIEVED`` row; the untrusted text of the evidence never goes into either.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from aml.assistant.citations import Citation, join_citations, primary, to_citation
from aml.assistant.evidence import Evidence
from aml.assistant.llm import ChatMessage, LLMClient, LLMError, get_llm
from aml.assistant.prompts import (
    ANSWER_PROMPT_VERSION,
    RETRY_MESSAGE,
    answer_schema,
    build_messages,
)
from aml.assistant.validation import (
    ISSUES,
    Checked,
    Claim,
    ModelOutputError,
    check_claims,
    parse_model_answer,
)
from aml.cases.runner import CaseError
from aml.cases.view import load_case
from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database

if TYPE_CHECKING:  # 8b's retrieve module pulls in neo4j-graphrag: imported only when needed
    from aml.assistant.retrieve import Retrieval

LANGUAGES = ("vi", "en")
REFUSAL = {"vi": "Không đủ bằng chứng.", "en": "Insufficient evidence."}
UNVERIFIED = {"vi": "[CHƯA KIỂM CHỨNG]", "en": "[UNVERIFIED]"}
SOURCES = {"vi": "Nguồn:", "en": "Sources:"}
DECISIONS = ("ANSWERED", "INSUFFICIENT_EVIDENCE", "FAILED", "NARRATIVE_DRAFTED")
QUESTION_MAX = 1000
FLAGGED_TEXT_MAX = 300  # characters of a flagged sentence kept in the audit row
MODULE = "assistant"

Retriever = Callable[..., "Retrieval"]  # same signature as aml.assistant.retrieve.retrieve


class AssistantError(RuntimeError):
    """The question could not be answered: bad input, or the model failed (not a refusal)."""


class AssistantInputError(AssistantError):
    """Bad input: question length, language or typology (the CLI exits with 2)."""


@dataclass(frozen=True)
class Sentence:
    text: str
    supported: bool
    citations: tuple[int, ...]  # Citation.n
    issues: tuple[str, ...]


@dataclass(frozen=True)
class Answer:
    answer_id: str
    case_id: str | None
    question: str
    language: str
    status: str  # "answered" | "insufficient_evidence"
    sentences: tuple[Sentence, ...]
    citations: tuple[Citation, ...]
    retrievers: tuple[str, ...]  # Retrieval.routes
    model: str
    prompt_version: str
    text: str  # one sentence per line, "<sentence> [n][m]"; the refusal text when refused
    refusal_reason: str | None  # "no_context" | "model" | "nothing_supported" | "unknown_case"
    discarded: tuple[Sentence, ...]  # sentences dropped when nothing was supported
    context: tuple[Evidence, ...]  # 8b's Evidence objects, untouched
    retrieval: Retrieval | None  # 8b's result, untouched; None when retrieval did not run
    llm_calls: int  # chat calls of this module (not Text2Cypher's)

    @property
    def refused(self) -> bool:
        return self.status == "insufficient_evidence"

    @property
    def flagged(self) -> tuple[Sentence, ...]:
        return tuple(s for s in (*self.sentences, *self.discarded) if not s.supported)

    @property
    def validation(self) -> dict[str, int]:
        supported = sum(s.supported for s in self.sentences)
        return {
            "sentences": len(self.sentences),
            "supported": supported,
            "unsupported": len(self.sentences) - supported,
        }

    def as_dict(self) -> dict[str, Any]:
        """The ``Answer`` contract of the UI (internal fields left out)."""
        return {
            "answer_id": self.answer_id,
            "case_id": self.case_id,
            "question": self.question,
            "language": self.language,
            "status": self.status,
            "sentences": [
                {"text": s.text, "supported": s.supported, "citations": list(s.citations)}
                for s in self.sentences
            ],
            "citations": [citation_dict(c) for c in self.citations],
            "retrievers": list(self.retrievers),
            "validation": self.validation,
            "model": self.model,
            "prompt_version": self.prompt_version,
        }


def citation_dict(c: Citation) -> dict[str, Any]:
    d = asdict(c)
    return {**d, "node_ids": list(c.node_ids), "txn_ids": list(c.txn_ids)}


# ---------------------------------------------------------------- defaults (tests patch these)
def default_llm(settings: Settings) -> LLMClient:
    return get_llm(settings)


def default_retriever(settings: Settings) -> Retriever:
    # imported here: the retrievers pull in neo4j-graphrag, which the pure modules do not need
    from aml.assistant.retrieve import retrieve

    return retrieve


# ---------------------------------------------------------------- building an answer (pure)
def number_citations(
    checked: Sequence[Checked], evidence: Sequence[Evidence]
) -> tuple[list[tuple[int, ...]], list[Citation]]:
    """Citation numbers per sentence and the citations, numbered 1..k by first appearance and
    merged by (kind, id). Items without an id give no number."""
    by_ref = {e.ref: e for e in evidence}
    numbers: dict[tuple[str, str], int] = {}
    citations: list[Citation] = []
    per_sentence = []
    for c in checked:
        mine: list[int] = []
        for ref in c.refs:
            key = primary(by_ref[ref])
            if key is None:
                continue
            if key not in numbers:
                numbers[key] = len(numbers) + 1
                citations.append(to_citation(by_ref[ref], numbers[key]))
            if numbers[key] not in mine:
                mine.append(numbers[key])
        per_sentence.append(tuple(mine))
    return per_sentence, citations


def answer_text(sentences: Sequence[Sentence], language: str) -> str:
    lines = []
    for s in sentences:
        shown = s.text if s.supported else f"{UNVERIFIED[language]} {s.text}"
        lines.append(join_citations(shown, s.citations))
    return "\n".join(lines)


def answer_id(case_id: str | None, language: str, question: str, model: str, text: str) -> str:
    """Same inputs, same id: asking again gives the same answer_id."""
    payload = json.dumps(
        [case_id, language, question, ANSWER_PROMPT_VERSION, model, text], ensure_ascii=False
    )
    return "ans-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def render_answer(answer: Answer) -> str:
    """``Answer.text``, then the sources (one ``[n] <kind> <id>`` line each)."""
    if not answer.citations:
        return answer.text
    sources = [f"[{c.n}] {c.kind} {c.id}" for c in answer.citations]
    return "\n".join([answer.text, "", SOURCES[answer.language], *sources])


# ---------------------------------------------------------------- the model call
class CountingClient:
    """Counts the chat calls made through it (the evaluation reads ``Answer.llm_calls``)."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.calls = 0

    def chat(self, messages: Sequence[ChatMessage], *, json_schema: dict[str, Any]) -> str:
        self.calls += 1
        return self.inner.chat(messages, json_schema=json_schema)


def chat_json(
    client: CountingClient,
    messages: list[ChatMessage],
    schema: dict[str, Any],
    parse: Callable[[str], Any],
    max_retries: int,
) -> Any:
    """The parsed reply. A reply that does not parse is asked again with RETRY_MESSAGE appended
    (a new prompt, so 8a's cache cannot return the broken reply), at most ``max_retries`` times;
    then `ModelOutputError` saying how many attempts were made. `LLMError` is not retried."""
    attempts = max_retries + 1
    for attempt in range(1, attempts + 1):
        try:
            return parse(client.chat(messages, json_schema=schema))
        except ModelOutputError:
            if attempt == attempts:
                raise ModelOutputError(
                    f"model output is not valid JSON after {attempts} attempt(s)"
                ) from None
            messages = [*messages, {"role": "user", "content": RETRY_MESSAGE}]
    raise AssertionError("unreachable")


@dataclass
class _Turn:
    """What one call of `answer_question` knows; it becomes an `Answer` and an audit row."""

    db: Database
    settings: Settings
    question: str
    case_id: str | None
    language: str
    mode: str
    actor: str | None
    model: str
    retrieval: Retrieval | None = None
    llm_calls: int = 0

    @property
    def evidence(self) -> tuple[Evidence, ...]:
        return tuple(self.retrieval.evidence) if self.retrieval is not None else ()

    def refuse(self, reason: str, discarded: Sequence[Sentence] = ()) -> Answer:
        return self.finish("insufficient_evidence", (), [], reason, discarded)

    def finish(
        self,
        status: str,
        sentences: Sequence[Sentence],
        citations: Sequence[Citation],
        refusal_reason: str | None,
        discarded: Sequence[Sentence] = (),
    ) -> Answer:
        text = answer_text(sentences, self.language) if sentences else REFUSAL[self.language]
        answer = Answer(
            answer_id=answer_id(self.case_id, self.language, self.question, self.model, text),
            case_id=self.case_id,
            question=self.question,
            language=self.language,
            status=status,
            sentences=tuple(sentences),
            citations=tuple(citations),
            retrievers=tuple(self.retrieval.routes) if self.retrieval is not None else (),
            model=self.model,
            prompt_version=ANSWER_PROMPT_VERSION,
            text=text,
            refusal_reason=refusal_reason,
            discarded=tuple(discarded),
            context=self.evidence,
            retrieval=self.retrieval,
            llm_calls=self.llm_calls,
        )
        decision = "ANSWERED" if status == "answered" else "INSUFFICIENT_EVIDENCE"
        self.record(decision, _reason(answer), answer)
        return answer

    def fail(self, message: str) -> AssistantError:
        self.record("FAILED", f"failed: {message}", None)
        return AssistantError(message)

    def record(self, decision: str, reason: str, answer: Answer | None) -> None:
        if answer is None:  # no answer to name the row after: the id of the question
            the_id = answer_id(self.case_id, self.language, self.question, self.model, "")
        else:
            the_id = answer.answer_id
        audit(
            self.db,
            module=MODULE,
            entity_type="case" if self.case_id is not None else "question",
            entity_id=self.case_id if self.case_id is not None else the_id,
            decision=decision,
            reason=reason,
            version=ANSWER_PROMPT_VERSION,
            actor=self.actor or self.settings.audit.system_actor,
            details=self.details(the_id, answer),
        )

    def details(self, the_id: str, answer: Answer | None) -> dict[str, Any]:
        """The 15 keys of the audit row. Ids and counts only, never the untrusted text."""
        r = self.retrieval
        sentences = answer.sentences if answer is not None else ()
        flagged = answer.flagged if answer is not None else ()
        return {
            "answer_id": the_id,
            "question": self.question,
            "language": self.language,
            "mode": self.mode,
            "retrievers": list(r.routes) if r is not None else [],
            "notes": [
                {"retriever": n.retriever, "status": n.status}
                for n in (r.notes if r is not None else ())
            ],
            "cypher": [
                {"attempt": q.attempt, "status": q.status, "rule": q.rule, "executed": q.executed}
                for q in (r.queries if r is not None else ())
            ],
            "retrieved_ids": list(dict.fromkeys(c for e in self.evidence for c in e.citations)),
            "cited_ids": [c.id for c in answer.citations] if answer is not None else [],
            "model": self.model,
            "prompt_version": ANSWER_PROMPT_VERSION,
            "validation": validation_counts(sentences, flagged),
            "flagged": flagged_details(flagged),
            "refusal_reason": answer.refusal_reason if answer is not None else None,
            "llm_calls": self.llm_calls,
        }


def flagged_details(flagged: Sequence[Sentence]) -> list[dict[str, Any]]:
    """Flagged sentences for an audit row. It is model text and may echo a memo, so it is cut."""
    return [{"text": s.text[:FLAGGED_TEXT_MAX], "issues": list(s.issues)} for s in flagged]


def validation_counts(sentences: Sequence[Sentence], flagged: Sequence[Sentence]) -> dict[str, Any]:
    supported = sum(s.supported for s in sentences)
    issues = {i: sum(i in s.issues for s in flagged) for i in ISSUES}
    return {
        "sentences": len(sentences),
        "supported": supported,
        "unsupported": len(sentences) - supported,
        "issues": {k: v for k, v in issues.items() if v},
    }


def _reason(a: Answer) -> str:
    context = f"{len(a.context)} context item(s)"
    if a.status == "answered":
        v = a.validation
        return (
            f"answered: {v['sentences']} sentence(s), {v['supported']} supported, "
            f"{v['unsupported']} flagged; {context}, {len(a.citations)} cited"
        )
    return (
        f"insufficient evidence ({a.refusal_reason}): {len(a.discarded)} sentence(s) "
        f"discarded; {context}"
    )


def _sentences(checked: Sequence[Checked], numbers: Sequence[tuple[int, ...]]) -> list[Sentence]:
    return [
        Sentence(c.text, c.supported, n, c.issues) for c, n in zip(checked, numbers, strict=True)
    ]


def _check_input(question: str, language: str) -> str:
    asked = question.strip()
    if not 1 <= len(asked) <= QUESTION_MAX:
        raise AssistantInputError(f"question must be 1 to {QUESTION_MAX} characters")
    if language not in LANGUAGES:
        raise AssistantInputError(f"language '{language}' is not available; choose vi or en")
    return asked


def _case_exists(db: Database, case_id: str) -> bool:
    try:
        load_case(db, case_id, masked=True, scored=False)
    except CaseError:
        return False
    return True


def answer_question(
    db: Database,
    settings: Settings,
    question: str,
    *,
    case_id: str | None = None,
    language: str | None = None,
    mode: str | None = None,
    actor: str | None = None,
    llm: LLMClient | None = None,
    retriever: Retriever | None = None,
) -> Answer:
    """A cited, post-checked answer, or a refusal (``status = "insufficient_evidence"``).

    An unknown case is a refusal (``unknown_case``), never an error. Bad input and a model that
    fails (invalid JSON after the retries, `LLMError`) raise `AssistantError`; 8b's
    `RetrievalError` / `RetrievalUnavailableError` and an unreachable Ollama pass through.
    """
    cfg = settings.assistant.answering
    lang = language or cfg.language
    asked = _check_input(question, lang)
    client = llm if llm is not None else default_llm(settings)
    fetch = retriever if retriever is not None else default_retriever(settings)
    turn = _Turn(db, settings, asked, case_id, lang, mode or cfg.mode, actor, client.chat_model)

    if case_id is not None and not _case_exists(db, case_id):
        return turn.refuse("unknown_case")
    try:
        turn.retrieval = fetch(
            db, settings, asked, case_id=case_id, mode=turn.mode, llm=client, actor=actor
        )
    except CaseError:
        return turn.refuse("unknown_case")
    evidence = turn.evidence
    if not evidence:
        return turn.refuse("no_context")

    messages = build_messages(asked, evidence, language=lang)
    schema = answer_schema([e.ref for e in evidence])
    counted = CountingClient(client)
    try:
        status, claims = chat_json(counted, messages, schema, parse_model_answer, cfg.max_retries)
    except ModelOutputError as exc:
        turn.llm_calls = counted.calls
        raise turn.fail(str(exc)) from exc
    except LLMError as exc:
        turn.llm_calls = counted.calls
        raise turn.fail(f"llm call failed: {exc}") from exc
    turn.llm_calls = counted.calls
    return _conclude(turn, status, claims)


def _conclude(turn: _Turn, status: str, claims: Sequence[Claim]) -> Answer:
    if status == "insufficient_evidence" or not claims:
        return turn.refuse("model")
    checked = check_claims(claims, turn.evidence)
    if not any(c.supported for c in checked):
        return turn.refuse("nothing_supported", _sentences(checked, [()] * len(checked)))
    numbers, citations = number_citations(checked, turn.evidence)
    return turn.finish("answered", _sentences(checked, numbers), citations, None)


def answer_events(
    db: Database, settings: Settings, question: str, **kwargs: Any
) -> Iterator[tuple[str, dict[str, Any]]]:
    """The hook for server-sent events: ``start`` then ``final`` (no ``token`` events yet)."""
    answer = answer_question(db, settings, question, **kwargs)
    yield (
        "start",
        {
            "answer_id": answer.answer_id,
            "case_id": answer.case_id,
            "language": answer.language,
        },
    )
    yield "final", {"answer": answer.as_dict()}
