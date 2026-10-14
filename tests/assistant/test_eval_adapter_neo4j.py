"""AC10 for specs/assistant-eval.md: the evaluation adapter on TINY with a real Neo4j.

The fixture wipes the dev Neo4j, syncs TINY into it, builds the knowledge layer from
`docs/knowledge/` with fake 64-dimension embeddings and wipes again at the end. After pytest the
dev graph has to be rebuilt (`aml graph sync --full`, `aml rag build --full`). The chat model is a
`FakeLLM` that answers every answer prompt with one sentence citing the first evidence item, so
Ollama is not needed.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import PROJECT_ROOT, Settings, get_settings, load_settings
from aml.common.db import DuckDb
from tests.network.conftest import er_template, tiny_env, tiny_parquet  # noqa: F401 (fixtures)

from .ev_helpers import cli, count, golden_mod, jsonl, model, ratio, runner_mod

pytestmark = pytest.mark.neo4j

QUESTIONS = "{fact: 4, multi_hop: 3, typology: 0, unanswerable: 4, injection: 4}"


def adapter() -> Any:
    from aml.assistant.eval import adapter as module

    return module


def _reply(messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any] | None) -> str:
    """A valid 8c answer citing the first evidence item; anything else gets an empty object."""
    try:
        refs = schema["properties"]["sentences"]["items"]["properties"]["cites"]["items"]["enum"]
    except (KeyError, TypeError):
        return "{}"  # not an answer prompt (Text2Cypher): its retriever reports a failure
    sentence = {"text": "Bằng chứng liên quan tới câu hỏi.", "cites": [refs[0]]}
    return json.dumps({"status": "answered", "sentences": [sentence]}, ensure_ascii=False)


class AEnv:
    def __init__(self, settings: Settings, db_path: Path, out: Path) -> None:
        self.settings = settings
        self.db_path = db_path
        self.out = out
        self.fake = _llm().FakeLLM(dim=64, responder=_reply)

    def chats(self) -> int:
        return sum(c["kind"] == "chat" for c in self.fake.calls)

    def run(self, out: Path, **kw: Any) -> Any:
        golden = golden_mod().read_golden(self.out)
        with DuckDb(self.db_path) as db:
            fn = adapter().build_answer_fn(db, self.settings, llm=self.fake, actor="eval")
            return runner_mod().run_eval(
                db,
                self.settings,
                golden,
                answer_fn=fn,
                key=adapter().run_key(self.settings),
                results_dir=out,
                knowledge_support=adapter().knowledge_support(self.settings),
                **kw,
            )


def _llm() -> Any:
    from aml.assistant import llm

    return llm


def _wipe(driver: Any, settings: Settings) -> None:
    from aml.graph.neo4j import client

    client.run_write_file(driver, settings, "knowledge/wipe.cypher")
    client.run_write_file(driver, settings, "sync/wipe.cypher")


@pytest.fixture
def aenv(
    er_template: Path,  # noqa: F811
    tiny_env: Any,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[AEnv]:
    from aml.assistant.knowledge.build import build_knowledge
    from aml.graph.neo4j import client
    from aml.graph.neo4j.sync import run_sync

    out = tmp_path / "eval"
    env = {
        **tiny_env(),
        "AML__RAG_EVAL__QUESTIONS": QUESTIONS,
        "AML__RAG_EVAL__RESULTS_DIR": str(out),
        "AML__ASSISTANT__PROVIDER": "fake",
        "AML__ASSISTANT__EMBEDDING__DIMENSIONS": "64",
        "AML__ASSISTANT__KNOWLEDGE__DIR": str(PROJECT_ROOT / "docs" / "knowledge"),
        "AML__ASSISTANT__CACHE__DIR": str(tmp_path / "cache"),
    }
    db_path = Path(env["AML__DB__DUCKDB_PATH"])
    shutil.copy(er_template, db_path)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    settings = load_settings()  # with .env: the Neo4j password
    assert cli("rag", "eval", "--golden-only").exit_code == 0

    driver = client.open_driver(settings)
    try:
        _wipe(driver, settings)
        with DuckDb(db_path) as db:
            run_sync(db, settings, full=True)
            build_knowledge(db, settings, _llm().FakeLLM(dim=64), full=True)
        yield AEnv(settings, db_path, out)
    finally:
        try:
            _wipe(driver, settings)
        finally:
            driver.close()
            get_settings.cache_clear()


def _last_audit_id(db: DuckDb) -> int:
    return int(db.query_df("SELECT COALESCE(MAX(audit_id), 0) FROM audit_log").iloc[0, 0])


def test_ac10_limit_3_then_a_rerun_then_neo4j_down(
    aenv: AEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = adapter().run_key(aenv.settings)
    assert isinstance(key, model().RunKey)
    assert key.llm_model and key.embed_model and key.prompt_version

    with DuckDb(aenv.db_path) as db:
        before = {t: count(db, t) for t in ("case_dispositions", "cases")}
        last_audit = _last_audit_id(db)
    first = aenv.run(aenv.out, limit=3)
    meta = first.meta
    assert (meta["asked"], meta["items_answered"], meta["partial"], meta["errors"]) == (
        6,
        3,
        True,
        0,
    )
    assert list(first.metrics) == ["vector", "graphrag"]
    assert (meta["llm_model"], meta["embed_model"], meta["prompt_version"]) == (
        key.llm_model,
        key.embed_model,
        key.prompt_version,
    )
    assert meta["side_effects"] == {}
    records = jsonl(aenv.out / "eval_answers.jsonl")
    assert len(records) == 6
    for record in records:
        assert record["text"], record
        assert record["seconds"] >= 0
        if record["mode"] == "vector":
            assert record["context_text"] == ""

    with DuckDb(aenv.db_path) as db:
        assert {t: count(db, t) for t in before} == before
        rows = db.query_df(
            f"SELECT module, decision FROM audit_log WHERE audit_id > {last_audit} "
            "ORDER BY audit_id"
        )
    written = [(str(m), str(d)) for m, d in rows.itertuples(index=False)]
    assert not [w for w in written if w[0] == "cases"]
    assert [w for w in written if w[1] == "EVALUATED"] == [("assistant", "EVALUATED")]
    allowed = {
        "EVALUATED",
        "RETRIEVED",
        "CYPHER_EXECUTED",
        "CYPHER_REJECTED",
        "CYPHER_FAILED",
        "ANSWERED",
        "INSUFFICIENT_EVIDENCE",
    }
    assert {d for _, d in written} <= allowed, written

    chats = aenv.chats()
    again = aenv.run(aenv.out, limit=3)
    assert (again.meta["asked"], again.meta["reused"]) == (0, 6)
    assert aenv.chats() == chats

    # Neo4j down: what is stored is reused; anything still to ask is refused before it is asked.
    monkeypatch.setenv("AML__NEO4J__URI", "bolt://127.0.0.1:1")
    get_settings.cache_clear()
    done = cli("rag", "eval", "--limit", "3")
    assert done.exit_code == 0, done.output
    assert "asked=0 reused=6" in done.stdout
    done = cli("rag", "eval", "--limit", "4")
    assert done.exit_code == 1, done.output
    assert "not available" in done.stderr
    assert len(jsonl(aenv.out / "eval_answers.jsonl")) == 6


def test_ac10_injection_memo_reaches_graphrag_context_only(aenv: AEnv, tmp_path: Path) -> None:
    r = aenv.run(tmp_path / "d2", types=("injection",), limit=1)
    assert (r.meta["asked"], r.meta["errors"]) == (2, 0)
    assert r.metrics["graphrag"].injection_exposed == ratio(1, 1)
    assert r.metrics["vector"].injection_exposed == ratio(0, 1)
    assert r.metrics["vector"].injection_resistance == ratio(0, 0)
    golden = golden_mod().read_golden(aenv.out)
    phrase = next(i for i in golden.items if i.id == "G-I01").injection_phrase
    (graph,) = [x for x in jsonl(tmp_path / "d2" / "eval_answers.jsonl") if x["mode"] == "graphrag"]
    assert phrase in graph["context_text"]
