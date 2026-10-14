"""Bodies of `aml rag build|status`: produce the output lines; `cli.py` only prints them."""

from __future__ import annotations

from aml.assistant.knowledge.build import build_knowledge, knowledge_status
from aml.assistant.knowledge.docs import load_corpus
from aml.assistant.knowledge.model import ENTITY_KEYS
from aml.assistant.llm import get_llm
from aml.common.config import Settings
from aml.common.db import get_db

FAKE_WARNING = "FAKE embeddings in use: retrieval results are not meaningful"


def dry_run_line(settings: Settings) -> str:
    """Read and validate the documents only: no database, Neo4j, Ollama, cache or audit."""
    a = settings.assistant
    corpus = load_corpus(settings.path(a.knowledge.dir), max_chars=a.knowledge.chunk_max_chars)
    kinds = {label: sum(e.label == label for e in corpus.entities) for label in ENTITY_KEYS}
    return (
        f"dry_run documents={len(corpus.docs)} chunks={len(corpus.chunks)} "
        f"typologies={kinds['Typology']} red_flags={kinds['RedFlag']} "
        f"procedures={kinds['Procedure']} regulations={kinds['Regulation']} "
        f"relations={len(corpus.relations)} mentions={sum(len(c.mentions) for c in corpus.chunks)}"
    )


def build_lines(settings: Settings, *, full: bool, actor: str) -> tuple[list[str], list[str]]:
    """Run a build; return (stdout lines, stderr lines)."""
    llm = get_llm(settings)
    with get_db(settings) as db:
        r = build_knowledge(db, settings, llm, full=full, actor=actor)
    out = (
        f"build_id={r.build_id} documents={r.documents} chunks={r.chunks} "
        f"embedded={r.embedded} cache_hits={r.cache_hits} "
        f"typologies={r.entities['Typology']} red_flags={r.entities['RedFlag']} "
        f"procedures={r.entities['Procedure']} regulations={r.entities['Regulation']} "
        f"relations={r.relations} mentions={r.mentions} cases={r.cases} matches={r.matches} "
        f"matches_skipped={r.matches_skipped} cases_unlinked={r.cases_unlinked} "
        f"seconds={r.seconds}"
    )
    err = [FAKE_WARNING] if settings.assistant.provider == "fake" else []
    return [out], err


def status_lines(settings: Settings) -> list[str]:
    with get_db(settings) as db:
        st = knowledge_status(db, settings)
    return [
        f"build_id={st.build_id}",
        f"built_at={st.built_at:%Y-%m-%dT%H:%M:%S}",
        f"embed_model={st.embed_model}",
        f"index={st.index_state}",
        f"dimensions={st.index_dimensions}",
        f"documents={st.documents}",
        f"chunks={st.chunks}",
        f"chunks_without_embedding={st.chunks_without_embedding}",
        f"typologies={st.entities['Typology']}",
        f"red_flags={st.entities['RedFlag']}",
        f"procedures={st.entities['Procedure']}",
        f"regulations={st.entities['Regulation']}",
        f"cases={st.cases}",
        f"matches={st.matches}",
        f"cases_unlinked={st.cases_unlinked}",
        f"corpus_in_sync={st.corpus_in_sync}",
        f"cases_in_sync={st.cases_in_sync}",
    ]


def retrieve_text(
    settings: Settings, question: str, *, case_id: str | None, mode: str, actor: str
) -> str:
    """Body of `aml rag retrieve` (Phase 8b): a header line, the notes, then the evidence."""
    # imported here: the retrievers pull in neo4j-graphrag, which no other `aml` command needs
    from aml.assistant.evidence import render_evidence
    from aml.assistant.retrieve import retrieve

    with get_db(settings) as db:
        r = retrieve(db, settings, question, case_id=case_id, mode=mode, actor=actor)
    lines = [
        f"mode={r.mode} routes={'+'.join(r.routes)} evidence={len(r.evidence)} "
        f"notes={len(r.notes)} seconds={r.seconds}"
    ]
    lines += [f"note: {n.retriever} {n.status}: {n.message}" for n in r.notes]
    return "\n".join([*lines, "", render_evidence(r.evidence)]) + "\n"
