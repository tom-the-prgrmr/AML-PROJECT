"""Build the knowledge layer in Neo4j: documents, chunks, entities, cases and typology matches.

Steps are numbered as in specs/assistant-knowledge.md. Everything that can fail without touching
Neo4j (reading the documents, embedding them, checking the vector length) comes first; every
write runs a `.cypher` file under `knowledge/` through `client.run_write_file`.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import neo4j
import pandas as pd

from aml.assistant.knowledge.docs import embed_text, load_corpus
from aml.assistant.knowledge.matches import TypologyMatch, derive_matches, rule_typologies
from aml.assistant.knowledge.model import (
    ENTITY_KEYS,
    KNOWLEDGE_VERSION,
    VECTOR_INDEX,
    Corpus,
    KnowledgeError,
)
from aml.assistant.llm import CachedLLM, LLMClient
from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.neo4j import client
from aml.graph.neo4j.session import shared_driver

ENTITY_FILES = {
    "Typology": "typology",
    "RedFlag": "red_flag",
    "Procedure": "procedure",
    "Regulation": "regulation",
}
RELATION_FILES = {
    "HAS_RED_FLAG": "has_red_flag",
    "INVESTIGATED_BY": "investigated_by",
    "GOVERNED_BY": "governed_by",
    "REQUIRED_BY": "required_by",
}
NOT_BUILT = "knowledge layer not built: run aml rag build"


@dataclass(frozen=True)
class BuildResult:
    build_id: int
    documents: int
    chunks: int
    embedded: int  # texts actually sent to the embedding client (cache misses)
    cache_hits: int
    entities: dict[str, int]  # 4 keys = labels
    relations: int  # the 4 types of RELATIONS
    mentions: int
    cases: int
    matches: int
    matches_skipped: int  # typology not in the corpus
    cases_unlinked: int  # case whose golden customer has no Customer node
    seconds: float


@dataclass(frozen=True)
class KnowledgeStatus:
    build_id: int
    built_at: datetime
    embed_model: str
    index_state: str  # "ONLINE" | ... | "MISSING"
    index_dimensions: int
    documents: int
    chunks: int
    chunks_without_embedding: int
    entities: dict[str, int]
    cases: int
    matches: int
    cases_unlinked: int
    corpus_in_sync: bool  # stored corpus_sha256 == sha256 of the directory now
    cases_in_sync: bool  # stored case_run_id == MAX(run_id) of case_runs


# ---------------------------------------------------------------- reads
def _frame(db: Database, name: str) -> list[dict[str, Any]]:
    text = db.sql_file(f"assistant/{name}").read_text(encoding="utf-8").strip().rstrip(";")
    df = db.query_df(text)
    df.columns = [str(c).lower() for c in df.columns]
    return df.to_dict("records")


def _dt(value: Any) -> datetime:
    return pd.Timestamp(value).to_pydatetime()


def _case_run_id(db: Database) -> int | None:
    value = _frame(db, "case_run.sql")[0]["run_id"]
    return None if value is None or bool(pd.isna(value)) else int(value)


def _case_rows(db: Database) -> list[dict[str, Any]]:
    return [
        {
            "case_id": str(r["case_id"]),
            "golden_customer_id": str(r["golden_customer_id"]),
            "status": str(r["status"]),
            "window_start": _dt(r["window_start"]),
            "first_alert_ts": _dt(r["first_alert_ts"]),
            "last_alert_ts": _dt(r["last_alert_ts"]),
            "alerts": int(r["alerts"]),
            "sources": str(r["sources"]),
        }
        for r in _frame(db, "cases.sql")
    ]


def _graph_counts(driver: neo4j.Driver, settings: Settings) -> dict[str, int]:
    frame = client.run_read_file(driver, settings, "read/knowledge_counts.cypher")
    return {str(k): int(v) for k, v in zip(frame["name"], frame["n"], strict=True)}


def _index(driver: neo4j.Driver, settings: Settings) -> tuple[str, int] | None:
    """(state, dimensions) of the vector index, or None when it does not exist."""
    frame = client.run_read_file(driver, settings, "read/knowledge_index.cypher")
    if frame.empty:
        return None
    row = frame.iloc[0]
    return str(row["state"]), int(row["dimensions"])


def _state(driver: neo4j.Driver, settings: Settings) -> dict[str, Any] | None:
    frame = client.run_read_file(driver, settings, "read/knowledge_state.cypher")
    return None if frame.empty else frame.iloc[0].to_dict()


# ---------------------------------------------------------------- rows for the MERGE files
def _doc_rows(corpus: Corpus) -> list[dict[str, Any]]:
    return [
        {
            "doc_id": d.doc_id,
            "title": d.title,
            "doc_type": d.doc_type,
            "version": d.version,
            "effective_date": d.effective_date,
            "language": d.language,
            "source_file": d.source_file,
            "sha256": d.sha256,
        }
        for d in corpus.docs
    ]


def _entity_rows(corpus: Corpus, label: str) -> list[dict[str, Any]]:
    by_rule = rule_typologies()
    rows = []
    for e in corpus.entities:
        if e.label != label:
            continue
        row: dict[str, Any] = {"id": e.id, "name": e.name, "doc_id": e.doc_id}
        if label == "Typology":
            row["rule_ids"] = sorted(r for r, t in by_rule.items() if t == e.id)
        rows.append(row)
    return rows


def _chunk_rows(corpus: Corpus, vectors: Sequence[Sequence[float]]) -> list[dict[str, Any]]:
    docs = {d.doc_id: d for d in corpus.docs}
    return [
        {
            "chunk_id": c.chunk_id,
            "doc_id": c.doc_id,
            "seq": c.seq,
            "heading": c.heading,
            "text": c.text,
            "embedding": [float(x) for x in vector],
            "doc_version": docs[c.doc_id].version,
            "effective_date": docs[c.doc_id].effective_date,
            "language": docs[c.doc_id].language,
        }
        for c, vector in zip(corpus.chunks, vectors, strict=True)
    ]


def _next_rows(corpus: Corpus) -> list[dict[str, Any]]:
    return [
        {"chunk_id": a.chunk_id, "next_id": b.chunk_id}
        for a, b in zip(corpus.chunks, corpus.chunks[1:], strict=False)
        if a.doc_id == b.doc_id
    ]


def _mention_rows(corpus: Corpus, label: str) -> list[dict[str, Any]]:
    labels = {e.id: e.label for e in corpus.entities}
    return [
        {"chunk_id": c.chunk_id, "target": target}
        for c in corpus.chunks
        for target in c.mentions
        if labels[target] == label
    ]


def _relation_rows(corpus: Corpus, kind: str) -> list[dict[str, Any]]:
    return [{"source": r.source, "target": r.target} for r in corpus.relations if r.type == kind]


# ---------------------------------------------------------------- build
def _embed(
    corpus: Corpus, settings: Settings, llm: LLMClient
) -> tuple[list[list[float]], int, int]:
    """Step 2: one embed call for the whole corpus -> (vectors, embedded, cache_hits)."""
    docs = {d.doc_id: d for d in corpus.docs}
    texts = [embed_text(docs[c.doc_id], c) for c in corpus.chunks]
    hits, misses = (llm.hits, llm.misses) if isinstance(llm, CachedLLM) else (0, 0)
    vectors = llm.embed(texts)
    if isinstance(llm, CachedLLM):
        embedded, cache_hits = llm.misses - misses, llm.hits - hits
    else:
        embedded, cache_hits = len(texts), 0
    expected = settings.assistant.embedding.dimensions
    for vector in vectors:
        if len(vector) != expected:
            raise KnowledgeError(f"embedding has {len(vector)} dimensions, expected {expected}")
    return vectors, embedded, cache_hits


def _load(
    driver: neo4j.Driver, settings: Settings, name: str, rows: list[dict[str, Any]], build_id: int
) -> None:
    client.run_write_file(
        driver, settings, f"knowledge/{name}.cypher", {"build_id": build_id}, rows=rows
    )


def _match_rows(matches: Sequence[TypologyMatch]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": m.case_id,
            "typology_id": m.typology_id,
            "evidence_ids": list(m.evidence_ids),
            "alert_keys": list(m.alert_keys),
            "rule_ids": list(m.rule_ids),
            "reason": m.reason,
        }
        for m in matches
    ]


def _write_corpus(
    driver: neo4j.Driver,
    settings: Settings,
    corpus: Corpus,
    vectors: Sequence[Sequence[float]],
    build_id: int,
) -> None:
    """Step 5: documents, entities, chunks, then the relations between them."""
    _load(driver, settings, "merge_documents", _doc_rows(corpus), build_id)
    for label, name in ENTITY_FILES.items():
        _load(driver, settings, f"merge_entities_{name}", _entity_rows(corpus, label), build_id)
    _load(driver, settings, "merge_chunks", _chunk_rows(corpus, vectors), build_id)
    _load(driver, settings, "merge_next", _next_rows(corpus), build_id)
    for label, name in ENTITY_FILES.items():
        _load(driver, settings, f"merge_mentions_{name}", _mention_rows(corpus, label), build_id)
    for kind, name in RELATION_FILES.items():
        _load(driver, settings, f"merge_relations_{name}", _relation_rows(corpus, kind), build_id)


def _write_cases(
    db: Database,
    driver: neo4j.Driver,
    settings: Settings,
    corpus: Corpus,
    build_id: int,
    case_run_id: int | None,
) -> tuple[int, int, int]:
    """Step 6: every case, then its typology matches -> (cases, matches, matches_skipped)."""
    cases = _case_rows(db)
    params = {"build_id": build_id, "case_run_id": case_run_id}
    client.run_write_file(driver, settings, "knowledge/merge_cases.cypher", params, rows=cases)
    known = {e.id for e in corpus.entities if e.label == "Typology"}
    derived = derive_matches(db)
    matches = [m for m in derived if m.typology_id in known]
    _load(driver, settings, "merge_matches", _match_rows(matches), build_id)
    return len(cases), len(matches), len(derived) - len(matches)


def build_knowledge(
    db: Database,
    settings: Settings,
    llm: LLMClient,
    *,
    full: bool = False,
    actor: str | None = None,
) -> BuildResult:
    """Build (or refresh) the knowledge layer. A failure before step 3 writes nothing."""
    started = time.perf_counter()
    a = settings.assistant
    dimensions = a.embedding.dimensions
    # 1-2. Read the documents and embed them; Neo4j is not opened yet.
    corpus = load_corpus(settings.path(a.knowledge.dir), max_chars=a.knowledge.chunk_max_chars)
    vectors, embedded, cache_hits = _embed(corpus, settings, llm)
    # 3. Open Neo4j; a vector index of another size is replaced only on request.
    driver = shared_driver(settings)
    index = _index(driver, settings)
    if full:
        client.run_write_file(driver, settings, "knowledge/wipe.cypher")
    elif index is not None and index[1] != dimensions:
        raise KnowledgeError(
            f"vector index {VECTOR_INDEX} has {index[1]} dimensions but "
            f"assistant.embedding.dimensions is {dimensions}: run aml rag build --full"
        )
    # 4. Constraints and the vector index.
    client.run_write_file(driver, settings, "knowledge/schema.cypher")
    config = {"vector.dimensions": dimensions, "vector.similarity_function": "cosine"}
    client.run_write_file(
        driver, settings, "knowledge/vector_index.cypher", {"options": {"indexConfig": config}}
    )
    # 5-6. Documents, entities, chunks; then cases and matches.
    previous = _state(driver, settings)
    build_id = (int(previous["build_id"]) if previous else 0) + 1
    _write_corpus(driver, settings, corpus, vectors, build_id)
    case_run_id = _case_run_id(db)
    cases, matches, skipped = _write_cases(db, driver, settings, corpus, build_id, case_run_id)
    # 7-8. Sweep what this build did not stamp, wait for the index, save the state, audit.
    client.run_write_file(driver, settings, "knowledge/sweep.cypher", {"build_id": build_id})
    client.run_write_file(driver, settings, "knowledge/await_indexes.cypher")
    unlinked = _graph_counts(driver, settings)["CaseUnlinked"]
    state = {
        "build_id": build_id,
        "embed_model": llm.embed_model,
        "dimensions": dimensions,
        "corpus_sha256": corpus.sha256,
        "case_run_id": case_run_id,
        "source_backend": db.backend,
        "version": KNOWLEDGE_VERSION,
    }
    client.run_write_file(driver, settings, "knowledge/save_state.cypher", state)
    result = BuildResult(
        build_id=build_id,
        documents=len(corpus.docs),
        chunks=len(corpus.chunks),
        embedded=embedded,
        cache_hits=cache_hits,
        entities={label: len(_entity_rows(corpus, label)) for label in ENTITY_KEYS},
        relations=len(corpus.relations),
        mentions=sum(len(c.mentions) for c in corpus.chunks),
        cases=cases,
        matches=matches,
        matches_skipped=skipped,
        cases_unlinked=unlinked,
        seconds=round(time.perf_counter() - started, 2),
    )
    _audit(db, result, state, full, actor)
    return result


def _audit(
    db: Database, result: BuildResult, state: dict[str, Any], full: bool, actor: str | None
) -> None:
    details = {k: v for k, v in asdict(result).items() if k != "seconds"}
    details.update(
        embed_model=state["embed_model"],
        dimensions=state["dimensions"],
        corpus_sha256=state["corpus_sha256"],
        case_run_id=state["case_run_id"],
        full=full,
    )
    extra: dict[str, Any] = {"actor": actor} if actor else {}
    audit(
        db,
        module="assistant",
        entity_type="knowledge_build",
        entity_id=str(result.build_id),
        decision="KNOWLEDGE_BUILD_COMPLETED",
        reason=(
            f"Built the knowledge layer: {result.documents} document(s), {result.chunks} "
            f"chunk(s), {result.cases} case(s), {result.matches} typology match(es)."
        ),
        version=KNOWLEDGE_VERSION,
        details=details,
        **extra,
    )


def knowledge_status(db: Database, settings: Settings) -> KnowledgeStatus:
    """What is in Neo4j now, and whether it still matches the documents and the cases. Read-only."""
    driver = shared_driver(settings)
    state = _state(driver, settings)
    if state is None:
        raise KnowledgeError(NOT_BUILT)
    index = _index(driver, settings)
    counts = _graph_counts(driver, settings)
    a = settings.assistant
    try:
        corpus_sha = load_corpus(
            settings.path(a.knowledge.dir), max_chars=a.knowledge.chunk_max_chars
        ).sha256
    except KnowledgeError:  # documents that cannot be read are certainly not what was built
        corpus_sha = None
    stored_run = state["case_run_id"]
    stored_run = None if stored_run is None or bool(pd.isna(stored_run)) else int(stored_run)
    return KnowledgeStatus(
        build_id=int(state["build_id"]),
        built_at=state["built_at"],
        embed_model=str(state["embed_model"]),
        index_state=index[0] if index else "MISSING",
        index_dimensions=index[1] if index else 0,
        documents=counts["Document"],
        chunks=counts["Chunk"],
        chunks_without_embedding=counts["ChunkWithoutEmbedding"],
        entities={label: counts[label] for label in ENTITY_KEYS},
        cases=counts["Case"],
        matches=counts["MATCHES_TYPOLOGY"],
        cases_unlinked=counts["CaseUnlinked"],
        corpus_in_sync=corpus_sha == state["corpus_sha256"],
        cases_in_sync=stored_run == _case_run_id(db),
    )
