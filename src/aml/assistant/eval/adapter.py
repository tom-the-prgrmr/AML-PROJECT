"""The one place where the evaluation reaches the assistant (8a knowledge, 8b/8c answers).

``eval/cli.py`` imports this module through ``load_adapter`` only, so the golden set, the scoring
and the report work without it. Nothing here opens a connection: Neo4j and Ollama are first
touched when a question is actually asked, so a rerun whose answers are all stored needs neither.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any

from aml.assistant.answering import Answer, answer_question
from aml.assistant.eval.metrics import knowledge_index
from aml.assistant.eval.model import AnswerFn, EvalAnswer, GoldenItem, RunKey
from aml.assistant.evidence import parse_citation
from aml.assistant.knowledge.docs import load_corpus
from aml.assistant.llm import ChatMessage, LLMClient, get_llm
from aml.assistant.prompts import ANSWER_PROMPT_VERSION
from aml.common.config import Settings
from aml.common.db import Database


def run_key(settings: Settings) -> RunKey:
    """What a stored answer depends on; read from the configuration, no service is touched."""
    return RunKey(
        llm_model=settings.ollama.llm_model,
        embed_model=settings.ollama.embed_model,
        prompt_version=ANSWER_PROMPT_VERSION,
    )


class CountingLLM:
    """Wraps an LLM client and counts the chat and embedding calls that go through it."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.chat_model = inner.chat_model
        self.embed_model = inner.embed_model
        self.seed = inner.seed
        self.num_ctx = inner.num_ctx
        self.chat_calls = 0
        self.embed_calls = 0

    def chat(
        self, messages: Sequence[ChatMessage], *, json_schema: Mapping[str, Any] | None = None
    ) -> str:
        self.chat_calls += 1
        return self.inner.chat(messages, json_schema=json_schema)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.embed_calls += 1
        return self.inner.embed(texts)


def cited_ids(answer: Answer) -> tuple[str, ...]:
    """Bare ids the answer cites: each citation's id and its transactions.

    An alert citation stands for its transactions: its own id (``RULE|ACCOUNT|TIME``) is not an
    id the golden set knows.
    """
    ids: dict[str, None] = {}  # insertion-ordered set
    for citation in answer.citations:
        own = () if citation.kind == "alert" else (citation.id,)
        ids |= dict.fromkeys((*own, *citation.txn_ids))
    return tuple(ids)


def to_eval_answer(answer: Answer, llm: CountingLLM) -> EvalAnswer:
    """Map the 8c answer to what the scorer reads."""
    return EvalAnswer(
        text=answer.text,
        citations=cited_ids(answer),
        flagged=tuple(s.text for s in answer.flagged),
        refused=answer.refused,
        context_ids=tuple(parse_citation(c)[1] for e in answer.context for c in e.citations),
        context_text="\n".join(
            u.text for e in answer.context for u in e.untrusted if u.field == "memo"
        ),
        chat_calls=llm.chat_calls,
        embed_calls=llm.embed_calls,
    )


def build_answer_fn(
    db: Database, settings: Settings, *, llm: Any = None, actor: str | None = None
) -> AnswerFn:
    """The answer function of a run. Errors are not caught here: the runner records them."""
    client: LLMClient = llm if llm is not None else get_llm(settings)  # opens no connection

    def answer(item: GoldenItem, mode: str) -> EvalAnswer:
        counting = CountingLLM(client)  # one per question: the counts are per answer
        result = answer_question(
            db,
            settings,
            item.question,
            case_id=item.case_id,
            language=item.language,
            mode=mode,
            actor=actor,
            llm=counting,
        )
        return to_eval_answer(result, counting)

    return answer


def knowledge_support(settings: Settings) -> Callable[[str], Collection[str]]:
    """Knowledge id (chunk, document, red flag) -> the typologies it is about."""
    knowledge = settings.assistant.knowledge
    index = knowledge_index(
        load_corpus(settings.path(knowledge.dir), max_chars=knowledge.chunk_max_chars)
    )
    return lambda knowledge_id: index.get(knowledge_id, frozenset())
