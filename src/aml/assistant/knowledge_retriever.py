"""Knowledge retriever: vector search over the document chunks, with optional graph expansion.

The search itself is done by the ``neo4j_graphrag`` retrievers, always through `GuardedDriver`:

* ``expand=False`` -- plain vector RAG: the chunks closest to the question.
* ``expand=True``  -- the same search plus, in the same query, the Typology / RedFlag / Procedure /
  Regulation nodes each chunk mentions; and, for the typologies a case matches
  (``seed_typologies``), the best chunk of each typology.

Chunk text and node names are document content: they travel as untrusted fields.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import neo4j
from neo4j_graphrag.retrievers import VectorCypherRetriever, VectorRetriever

from aml.assistant.evidence import (
    Evidence,
    RetrievalError,
    RetrievalUnavailableError,
    cite,
    fmt_day,
    is_citable,
    is_safe_token,
    renumber,
    untrusted_field,
)
from aml.assistant.graphrag_adapter import READ, GuardedDriver, LLMEmbedder
from aml.assistant.knowledge.model import VECTOR_INDEX
from aml.assistant.llm import LLMClient
from aml.common.config import Settings
from aml.common.db import ServiceUnavailableError
from aml.graph.neo4j.client import load_statements
from aml.graph.neo4j.guard import GraphError
from aml.graph.neo4j.session import shared_driver

CHUNK_PROPERTIES = ["chunk_id", "text", "doc_id", "doc_version", "effective_date"]
ENTITY_KINDS = {
    "Procedure": "procedure",
    "RedFlag": "red_flag",
    "Regulation": "regulation",
    "Typology": "typology",
}


class KnowledgeNotBuiltError(RetrievalError):
    """There is no vector index yet: ``aml rag build`` has not been run."""


def _native(value: Any) -> Any:
    to_native = getattr(value, "to_native", None)
    return to_native() if callable(to_native) else value


def _chunk(row: Mapping[str, Any], retriever: str, settings: Settings) -> Evidence | None:
    chunk_id, doc_id, version = row.get("chunk_id"), row.get("doc_id"), row.get("doc_version")
    if not (is_citable(chunk_id) and is_safe_token(doc_id) and is_safe_token(version)):
        return None  # ids come from the build and are always safe; anything else is not shown
    effective = _native(row.get("effective_date"))
    if not isinstance(effective, date):
        return None
    text = (
        f"Chunk {chunk_id} from document {doc_id} "
        f"(version {version}, effective {fmt_day(effective)})"
    )
    data = {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "doc_version": version,
        "effective_date": effective,
    }
    body = untrusted_field(
        "chunk_text", row.get("text"), settings.assistant.retrieval.max_chunk_chars
    )
    score = round(float(row["score"]), 4)
    return Evidence(
        "E0",
        "passage",
        retriever,
        "neo4j",
        text,
        (cite("chunk", str(chunk_id)),),
        data,
        body,
        score,
    )


def _linked(
    rows: Sequence[Mapping[str, Any]], kept: set[str], settings: Settings
) -> list[Evidence]:
    """One Evidence per knowledge node, citing every kept chunk that mentions it."""
    chunks: dict[tuple[str, str], list[str]] = {}
    names: dict[tuple[str, str], Any] = {}
    for row in rows:
        if row.get("chunk_id") not in kept:
            continue
        for node in row.get("linked") or []:
            key = (str(node.get("label")), str(node.get("id")))
            if key[0] in ENTITY_KINDS and is_citable(key[1]):
                chunks.setdefault(key, []).append(str(row["chunk_id"]))
                names[key] = node.get("name")
    out = []
    for label, key in sorted(chunks):
        ids = chunks[label, key]
        out.append(
            Evidence(
                "E0",
                "passage",
                "graph_expansion",
                "neo4j",
                f"{label} {key} is linked to chunk(s) {', '.join(ids)}",
                (cite(ENTITY_KINDS[label], key), *(cite("chunk", i) for i in ids)),
                {"label": label, "id": key, "chunk_ids": ids},
                untrusted_field(
                    "name", names[label, key], settings.assistant.retrieval.max_untrusted_chars
                ),
            )
        )
    return out


def _flatten(record: Mapping[str, Any]) -> dict[str, Any]:
    """A package record as one flat row (the plain retriever nests the chunk under ``node``)."""
    row = dict(record)
    node = row.pop("node", None)
    if isinstance(node, Mapping):
        row.update(node)
    return row


def knowledge(
    settings: Settings,
    question: str,
    *,
    llm: LLMClient,
    expand: bool = True,
    seed_typologies: Sequence[str] = (),
    index: str | None = None,
    driver: neo4j.Driver | None = None,
) -> list[Evidence]:
    """Chunks for the question (and, with ``expand``, the knowledge nodes around them).

    Neo4j down -> `RetrievalUnavailableError`, raised before the model is asked for an embedding.
    No vector index -> `KnowledgeNotBuiltError`.
    """
    if not question.strip():
        raise RetrievalError("question is empty")
    cfg = settings.assistant.retrieval
    try:
        guarded = GuardedDriver(driver or shared_driver(settings), settings)
        rows, vector = _search(guarded, settings, question, llm, expand, index or VECTOR_INDEX)
        rows = [r for r in rows if float(r["score"]) >= cfg.min_score]
        rows.sort(key=lambda r: (-float(r["score"]), str(r.get("chunk_id"))))
        found = [e for e in (_chunk(r, "vector", settings) for r in rows) if e is not None]
        kept = {str(e.data["chunk_id"]) for e in found}
        out = found + (_linked(rows, kept, settings) if expand else [])
        seeds = [t for t in dict.fromkeys(seed_typologies) if is_safe_token(t)]
        if seeds and cfg.max_typology_chunks > 0:
            (statement,) = load_statements("retrieval/typology_chunks.cypher")
            params = {
                "typology_ids": seeds,
                "vector": vector if vector is not None else llm.embed([question])[0],
                "limit": cfg.max_typology_chunks,
            }
            result = guarded.execute_query(statement, params, routing_=READ)
            extra = [_flatten(r) for r in result.records if r["chunk_id"] not in kept]
            out += [e for e in (_chunk(r, "graph_expansion", settings) for r in extra) if e]
    except ServiceUnavailableError as exc:
        raise RetrievalUnavailableError(f"neo4j not available: {exc}") from exc
    except neo4j.exceptions.Neo4jError as exc:
        raise GraphError(f"knowledge query failed: {exc.message or exc}") from exc
    return renumber(out)


def _search(
    guarded: GuardedDriver, settings: Settings, question: str, llm: LLMClient, expand: bool,
    index: str,
) -> tuple[list[dict[str, Any]], list[float] | None]:  # fmt: skip
    """Run the package's vector search; return flat rows and the question vector it used."""
    cfg = settings.assistant.retrieval
    common: dict[str, Any] = {
        "embedder": LLMEmbedder(llm),
        "neo4j_database": settings.neo4j.database,
    }
    try:
        if expand:
            (tail,) = load_statements("retrieval/expand_chunks.cypher")
            raw = VectorCypherRetriever(
                guarded, index, retrieval_query=tail, **common
            ).get_search_results(
                query_text=question,
                top_k=cfg.top_k,
                query_params={"min_score": cfg.min_score, "max_linked": cfg.max_linked_per_chunk},
            )
        else:
            raw = VectorRetriever(
                guarded, index, return_properties=CHUNK_PROPERTIES, **common
            ).get_search_results(query_text=question, top_k=cfg.top_k)
    except (GraphError, ServiceUnavailableError, neo4j.exceptions.Neo4jError):
        raise
    except Exception as exc:  # the package raises a bare Exception when the index is missing
        if "No index with name" in str(exc):
            raise KnowledgeNotBuiltError("knowledge layer not built: run aml rag build") from exc
        raise
    return [_flatten(r) for r in raw.records], (raw.metadata or {}).get("query_vector")
