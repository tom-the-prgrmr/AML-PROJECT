"""`retrieve()`: the one entry point of the retrieval layer.

Two modes share one signature and one result type, so the evaluation can compare them:

* ``vector``   -- plain vector RAG: chunk search only.
* ``graphrag`` -- the router picks the retrievers (transaction lookup, case graph, knowledge with
  graph expansion, Text2Cypher) and they run in the order of ``ROUTES``.

The layer is read-only. The only thing it writes is one ``RETRIEVED`` row in ``audit_log`` per
call, with the routes, the reasons and the ids handed to the model (never the untrusted text).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from aml.assistant.case_graph import case_graph
from aml.assistant.evidence import (
    Evidence,
    RetrievalError,
    RetrieverNote,
    fit_context,
    parse_citation,
    render_evidence,
)
from aml.assistant.knowledge_retriever import KnowledgeNotBuiltError, knowledge
from aml.assistant.llm import LLMClient, LLMError, get_llm
from aml.assistant.router import ROUTER_VERSION, RoutePlan, route
from aml.assistant.text2cypher import GeneratedQuery, Text2CypherError, text2cypher
from aml.assistant.txn_lookup import transaction_facts
from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.neo4j.guard import GraphError

MODES = ("graphrag", "vector")
RETRIEVAL_VERSION = "retrieval/v1"
QUESTION_LIMIT = 2000

__all__ = ["MODES", "RETRIEVAL_VERSION", "Retrieval", "RetrieverNote", "retrieve"]

Groups = list[tuple[str, Sequence[Evidence]]]


@dataclass(frozen=True)
class Retrieval:
    question: str
    case_id: str | None
    mode: str
    routes: tuple[str, ...]  # retrievers that ran; vector mode -> ("vector",)
    reasons: tuple[str, ...]
    evidence: tuple[Evidence, ...]  # refs E1..En, in the order of ROUTES; within the budget
    context_chars: int  # len(render_evidence(evidence)) <= assistant.retrieval.max_context_chars
    truncated: bool  # at least one "truncated" note
    notes: tuple[RetrieverNote, ...]
    queries: tuple[GeneratedQuery, ...]
    seconds: float


def _cited(evidence: Sequence[Evidence], kind: str) -> list[str]:
    """Ids of the ``kind:`` citations, in order of appearance, without repeats."""
    ids = [i for e in evidence for k, i in map(parse_citation, e.citations) if k == kind]
    return list(dict.fromkeys(ids))


def _run_knowledge(
    name: str, groups: Groups, notes: list[RetrieverNote], settings: Settings, question: str,
    llm: LLMClient, *, expand: bool, seeds: Sequence[str],
) -> None:  # fmt: skip
    """Chunk search; a model or index problem becomes a note instead of failing the call."""
    try:
        found = knowledge(settings, question, llm=llm, expand=expand, seed_typologies=tuple(seeds))
    except (LLMError, KnowledgeNotBuiltError) as exc:
        notes.append(RetrieverNote(name, "unavailable", str(exc)))
    except GraphError as exc:
        notes.append(RetrieverNote(name, "failed", str(exc)))
    else:
        groups.append((name, found))


def _run_text2cypher(
    groups: Groups, notes: list[RetrieverNote], db: Database, settings: Settings, question: str,
    llm: LLMClient, plan: RoutePlan, customer: str | None, actor: str | None,
) -> tuple[GeneratedQuery, ...]:  # fmt: skip
    try:
        result = text2cypher(
            db, settings, question, llm=llm, case_id=plan.case_id, golden_customer_id=customer,
            actor=actor,
        )  # fmt: skip
    except Text2CypherError as exc:
        notes.append(RetrieverNote("text2cypher", "failed", str(exc)))
        return ()
    except LLMError as exc:
        notes.append(RetrieverNote("text2cypher", "unavailable", str(exc)))
        return ()
    if not any(q.status == "EXECUTED" for q in result.queries):
        last = result.queries[-1].message if result.queries else "no query was generated"
        notes.append(RetrieverNote("text2cypher", "failed", f"no generated query ran: {last}"))
    groups.append(("text2cypher", result.evidence))
    return result.queries


def _graphrag(
    db: Database, settings: Settings, question: str, plan: RoutePlan, llm: LLMClient,
    actor: str | None,
) -> tuple[Groups, list[RetrieverNote], tuple[GeneratedQuery, ...]]:  # fmt: skip
    groups: Groups = []
    notes: list[RetrieverNote] = []
    queries: tuple[GeneratedQuery, ...] = ()
    case_evidence: list[Evidence] = []
    if "txn_lookup" in plan.routes:
        found = transaction_facts(db, settings, plan.txn_ids)
        if found:
            groups.append(("txn_lookup", found))
        else:
            message = f"no transaction found for: {', '.join(plan.txn_ids)}"
            notes.append(RetrieverNote("txn_lookup", "skipped", message))
    if "case_graph" in plan.routes:
        if plan.case_id is not None:
            case_evidence = case_graph(db, settings, case_id=plan.case_id)
        else:
            case_evidence = case_graph(db, settings, customer=plan.customer)
        groups.append(("case_graph", case_evidence))
    if "knowledge" in plan.routes:
        seeds = _cited(case_evidence, "typology")
        _run_knowledge(
            "knowledge", groups, notes, settings, question, llm, expand=True, seeds=seeds
        )
    if "text2cypher" in plan.routes:
        customer = next(iter(_cited(case_evidence, "customer")), None)
        queries = _run_text2cypher(
            groups, notes, db, settings, question, llm, plan, customer, actor
        )
    return groups, notes, queries


def retrieve(
    db: Database,
    settings: Settings,
    question: str,
    *,
    case_id: str | None = None,
    mode: str = "graphrag",
    llm: LLMClient | None = None,
    actor: str | None = None,
    record_audit: bool = True,
) -> Retrieval:
    """Evidence for ``question``, cut to the context budget, with refs E1..En.

    A model problem, a missing vector index or a failed generated query becomes a `RetrieverNote`.
    Neo4j being down, a stale graph, an unknown case and bad input are raised.
    """
    started = time.perf_counter()
    if not question.strip():
        raise RetrievalError("question is empty")
    if mode not in MODES:
        raise RetrievalError(f"unknown mode '{mode}'; choose one of: {', '.join(MODES)}")
    client = llm if llm is not None else get_llm(settings)
    groups: Groups = []
    notes: list[RetrieverNote] = []
    queries: tuple[GeneratedQuery, ...] = ()
    if mode == "vector":
        routes, reasons = ("vector",), ("vector: plain vector mode",)
        _run_knowledge("vector", groups, notes, settings, question, client, expand=False, seeds=())
    else:
        plan = route(
            question, case_id=case_id, text2cypher_enabled=settings.assistant.text2cypher.enabled
        )
        routes, reasons, case_id = plan.routes, plan.reasons, plan.case_id
        groups, notes, queries = _graphrag(db, settings, question, plan, client, actor)

    evidence, cut = fit_context(groups, settings.assistant.retrieval.max_context_chars)
    notes += cut
    result = Retrieval(
        question=question,
        case_id=case_id,
        mode=mode,
        routes=routes,
        reasons=reasons,
        evidence=tuple(evidence),
        context_chars=len(render_evidence(evidence)),
        truncated=bool(cut),
        notes=tuple(notes),
        queries=queries,
        seconds=round(time.perf_counter() - started, 3),
    )
    if record_audit:
        _audit(db, settings, result, actor)
    return result


def _audit(db: Database, settings: Settings, r: Retrieval, actor: str | None) -> None:
    """One RETRIEVED row: which retrievers ran, why, and which ids went to the model."""
    question_hash = hashlib.sha256(r.question.encode("utf-8")).hexdigest()[:16]
    audit(
        db,
        module="assistant",
        entity_type="retrieval",
        entity_id=r.case_id or question_hash,
        decision="RETRIEVED",
        reason=f"{r.mode}: {'+'.join(r.routes)} returned {len(r.evidence)} evidence item(s)",
        version=RETRIEVAL_VERSION,
        actor=actor or settings.audit.system_actor,
        details={
            "question": r.question[:QUESTION_LIMIT],
            "mode": r.mode,
            "case_id": r.case_id,
            "routes": list(r.routes),
            "reasons": list(r.reasons),
            "router_version": ROUTER_VERSION,
            "context_chars": r.context_chars,
            "truncated": r.truncated,
            "evidence": [
                {
                    "ref": e.ref,
                    "retriever": e.retriever,
                    "source": e.source,
                    "citations": list(e.citations),
                }
                for e in r.evidence
            ],
            "notes": [asdict(n) for n in r.notes],
        },
    )
