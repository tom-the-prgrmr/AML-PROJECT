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


# ---------------------------------------------------------------- Phase 8c: ask, narrative, explain
def ask_output(
    settings: Settings,
    question: str,
    *,
    case_id: str | None,
    language: str | None,
    mode: str | None,
    as_json: bool,
    actor: str,
) -> tuple[bytes, str]:
    """Body of `aml rag ask`: (stdout as UTF-8 bytes, the summary line for stderr)."""
    import json

    from aml.assistant.answering import answer_question, render_answer

    with get_db(settings) as db:
        a = answer_question(
            db, settings, question, case_id=case_id, language=language, mode=mode, actor=actor
        )
    text = json.dumps(a.as_dict(), ensure_ascii=False) if as_json else render_answer(a)
    v = a.validation
    summary = (
        f"answer_id={a.answer_id} status={a.status} supported={v['supported']} "
        f"unsupported={v['unsupported']}"
    )
    if a.refusal_reason is not None:
        summary += f" refusal={a.refusal_reason}"
    return (text + "\n").encode("utf-8"), summary


def narrative_output(
    settings: Settings, case_id: str, *, language: str | None, actor: str
) -> bytes:
    """Body of `aml rag narrative`: the markdown draft as file bytes (also what stdout gets)."""
    from aml.assistant.narrative import draft_narrative
    from aml.cases.narrative import as_file_bytes

    with get_db(settings) as db:
        d = draft_narrative(db, settings, case_id, language=language, actor=actor)
    return as_file_bytes(d.narrative.markdown)


def explain_lines(settings: Settings, case_id: str, *, typology: str | None) -> list[str]:
    """Body of `aml rag explain`: one header line, then a block per typology."""
    from aml.assistant.explainer import explain_typology

    with get_db(settings) as db:
        x = explain_typology(db, settings, case_id, typology=typology)
    lines = [f"case={x.case_id} typologies={len(x.typologies)} knowledge={x.knowledge}"]
    for t in x.typologies:
        lines.append(
            f"typology={t.typology} rules={','.join(t.rule_ids)} "
            f"transactions={t.transactions_total} chunks={len(t.chunks)}"
        )
        lines += [f"  definition: {line}" for line in t.definition.split("\n") if line]
        for r in t.transactions:
            when = r["txn_ts"].replace("T", " ")
            src, dst = r["from_account_id"] or "-", r["to_account_id"] or "-"
            lines.append(f"  {r['txn_id']} {when} {src} -> {dst} {r['amount_vnd']} {r['channel']}")
        lines += [f"  chunk {c['chunk_id']}" for c in t.chunks]
    return lines
