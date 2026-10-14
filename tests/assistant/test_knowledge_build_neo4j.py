"""AC9 for specs/assistant-knowledge.md: `build_knowledge` and `knowledge_status` on a real Neo4j.

Every test wipes the dev Neo4j first (`knowledge/wipe.cypher`, then `sync/wipe.cypher`; spec Q21 of
6a) and again at the end, so nothing depends on what an earlier test or another session left.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb
from aml.dba.edges import refresh_acct_edge_daily
from tests.cases.helpers import CASE_C01_A, CASE_C01_B, CASE_C05, load_minic, run_cases
from tests.neo4j_sync.helpers import CONSTRAINTS, client, one, read, rows_of, run_sync

from .kn_helpers import (
    KB_A,
    KB_C,
    assistant_audit,
    k_neo_settings,
    kbuild,
    kmodel,
    llm,
    mod,
    replace_once,
    write_file,
    write_mini_k,
)

pytestmark = pytest.mark.neo4j

LABELS = (
    "Document",
    "Chunk",
    "Typology",
    "RedFlag",
    "Procedure",
    "Regulation",
    "Case",
    "KnowledgeState",
)
RELS = (
    "PART_OF",
    "NEXT",
    "MENTIONS",
    "DEFINES",
    "HAS_RED_FLAG",
    "INVESTIGATED_BY",
    "REQUIRED_BY",
    "GOVERNED_BY",
    "ABOUT",
    "MATCHES_TYPOLOGY",
)
AFTER_R1 = {
    "Document": 2,
    "Chunk": 5,
    "Typology": 1,
    "RedFlag": 1,
    "Procedure": 1,
    "Regulation": 1,
    "Case": 5,
    "KnowledgeState": 1,
    "PART_OF": 5,
    "NEXT": 3,
    "MENTIONS": 5,
    "DEFINES": 4,
    "HAS_RED_FLAG": 1,
    "INVESTIGATED_BY": 1,
    "REQUIRED_BY": 1,
    "GOVERNED_BY": 0,
    "ABOUT": 0,
    "MATCHES_TYPOLOGY": 1,
}
CASE_KEYS = {
    "case_id",
    "golden_customer_id",
    "status",
    "window_start",
    "first_alert_ts",
    "last_alert_ts",
    "alerts",
    "sources",
    "case_run_id",
    "build_id",
}
REASON_R1 = "Built the knowledge layer: 2 document(s), 5 chunk(s), 5 case(s), 1 typology match(es)."
CHUNK_003_TEXT = "Structuring thử nghiệm — Dấu hiệu\nNộp tiền nhiều lần dưới ngưỡng."
VECTOR_QUERY = (
    "CALL db.index.vector.queryNodes('chunk_embedding', 1, $v) YIELD node, score "
    "RETURN node.chunk_id AS chunk_id, score"
)


class KEnv:
    def __init__(self, duck: DuckDb, mini_k: Path, cache: Path, settings: Settings, driver: Any):
        self.duck = duck
        self.mini_k = mini_k
        self.cache = cache
        self.settings = settings
        self.driver = driver
        self.llm = llm().CachedLLM(llm().FakeLLM(dim=64), cache)

    def build(self, **kw: Any) -> Any:
        return kbuild().build_knowledge(self.duck, self.settings, self.llm, **kw)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for label in LABELS:
            out[label] = int(one(self.driver, self.settings, f"MATCH (n:{label}) RETURN count(n)"))
        for rel in RELS:
            out[rel] = int(
                one(self.driver, self.settings, f"MATCH ()-[r:{rel}]->() RETURN count(r)")
            )
        return out

    def rows(self, cypher: str, params: Any = None) -> list[tuple[Any, ...]]:
        return rows_of(self.driver, self.settings, cypher, params)

    def one(self, cypher: str, params: Any = None) -> Any:
        return one(self.driver, self.settings, cypher, params)

    def status(self) -> Any:
        return kbuild().knowledge_status(self.duck, self.settings)


def _wipe(driver: Any, settings: Settings) -> None:
    c = client()
    c.run_write_file(driver, settings, "knowledge/wipe.cypher")
    c.run_write_file(driver, settings, "sync/wipe.cypher")


@pytest.fixture
def kenv(duck: DuckDb, tmp_path: Path) -> Iterator[KEnv]:
    mini_k = write_mini_k(tmp_path / "kb")
    cache = tmp_path / "cache"
    settings = k_neo_settings(mini_k, cache)
    load_minic(duck)
    run_cases(duck, settings)
    driver = client().open_driver(settings)
    try:
        _wipe(driver, settings)
        yield KEnv(duck, mini_k, cache, settings, driver)
    finally:
        try:
            _wipe(driver, settings)
        finally:
            driver.close()


def test_ac9_first_build_result(kenv: KEnv) -> None:
    r1 = kenv.build()
    assert r1.build_id == 1
    assert r1.documents == 2
    assert r1.chunks == 5
    assert r1.embedded == 5
    assert r1.cache_hits == 0
    assert r1.entities == {"Typology": 1, "RedFlag": 1, "Procedure": 1, "Regulation": 1}
    assert r1.relations == 3
    assert r1.mentions == 5
    assert r1.cases == 5
    assert r1.matches == 1
    assert r1.matches_skipped == 7
    assert r1.cases_unlinked == 5


def test_ac9_first_build_graph_contents(kenv: KEnv) -> None:
    kenv.build()
    assert kenv.counts() == AFTER_R1

    chunk = kenv.rows(
        "MATCH (c:Chunk {chunk_id: 'KB-TYP-901#003'}) RETURN c.doc_id, c.seq, c.heading, c.text, "
        "c.doc_version, c.effective_date, c.language, size(c.embedding)"
    )
    assert chunk == [
        (
            "KB-TYP-901",
            3,
            "Dấu hiệu",
            "Nộp tiền nhiều lần dưới ngưỡng.",
            "1.0",
            date(2026, 1, 1),
            "vi",
            64,
        )
    ]
    doc = kenv.rows(
        "MATCH (d:Document {doc_id: 'KB-SOP-901'}) RETURN d.version, d.doc_type, d.is_synthetic"
    )
    assert doc == [("2.1", "SOP", True)]
    typology = kenv.rows(
        "MATCH (t:Typology {typology_id: 'structuring'}) RETURN t.name, t.rule_ids"
    )
    assert typology == [("Chia nhỏ giao dịch", ["STRUCTURING"])]


def test_ac9_the_typology_match_carries_its_evidence_and_reason(kenv: KEnv) -> None:
    kenv.build()
    rows = kenv.rows(
        "MATCH (c:Case)-[m:MATCHES_TYPOLOGY]->(t:Typology) RETURN c.case_id, t.typology_id, "
        "m.evidence_ids, m.alert_keys, m.rule_ids, m.reason"
    )
    assert rows == [
        (
            CASE_C01_A,
            "structuring",
            ["T01"],
            ["STRUCTURING|A01|2026-03-02T09:00:00"],
            ["STRUCTURING"],
            "1 alert(s) from rule(s) STRUCTURING map to typology structuring",
        )
    ]


def test_ac9_case_nodes(kenv: KEnv) -> None:
    kenv.build()
    row = kenv.rows(
        f"MATCH (c:Case {{case_id: '{CASE_C05}'}}) RETURN c.golden_customer_id, c.status, "
        "c.alerts, c.sources, c.case_run_id"
    )
    assert row == [("G-C05", "OPEN", 1, "SCREENING", 1)]
    keys = {r[0] for r in kenv.rows("MATCH (c:Case) UNWIND keys(c) AS k RETURN DISTINCT k")}
    assert keys == CASE_KEYS


def test_ac9_vector_index_is_online_and_answers_queries(kenv: KEnv) -> None:
    kenv.build()
    index = kenv.rows(
        "SHOW INDEXES YIELD name, type, state WHERE name = 'chunk_embedding' "
        "RETURN name, type, state"
    )
    assert index == [("chunk_embedding", "VECTOR", "ONLINE")]

    vector = llm().fake_embedding(CHUNK_003_TEXT, 64)
    found = read(
        kenv.driver,
        kenv.settings,
        VECTOR_QUERY,
        {"v": vector},
        procedures=kenv.settings.assistant.vector_procedures,
    )
    assert len(found) == 1
    assert found.iloc[0]["chunk_id"] == "KB-TYP-901#003"
    assert found.iloc[0]["score"] >= 0.99

    write_blocked = mod("aml.graph.neo4j.guard").WriteBlockedError
    with pytest.raises(
        write_blocked,
        match=r"procedure db\.index\.vector\.queryNodes is not allowed in a read-only query",
    ):
        read(kenv.driver, kenv.settings, VECTOR_QUERY, {"v": vector})


def test_ac9_build_writes_one_audit_row(kenv: KEnv) -> None:
    kenv.build()
    rows = assistant_audit(kenv.duck)
    assert len(rows) == 1
    row = rows[0]
    assert row["entity_type"] == "knowledge_build"
    assert row["entity_id"] == "1"
    assert row["decision"] == "KNOWLEDGE_BUILD_COMPLETED"
    assert row["version"] == "knowledge/v1"
    assert row["reason"] == REASON_R1
    details = row["details"]
    assert details["embed_model"] == "fake-embed"
    assert details["dimensions"] == 64
    assert details["case_run_id"] == 1
    assert "seconds" not in details
    json.dumps(details)


def test_ac9_second_build_is_idempotent_and_status_is_in_sync(kenv: KEnv) -> None:
    kenv.build()
    r2 = kenv.build()
    assert r2.build_id == 2
    assert r2.embedded == 0
    assert r2.cache_hits == 5
    assert kenv.counts() == AFTER_R1
    assert len(assistant_audit(kenv.duck)) == 2

    status = kenv.status()
    assert status.build_id == 2
    assert status.embed_model == "fake-embed"
    assert status.index_state == "ONLINE"
    assert status.index_dimensions == 64
    assert status.documents == 2
    assert status.chunks == 5
    assert status.chunks_without_embedding == 0
    assert status.cases == 5
    assert status.matches == 1
    assert status.cases_unlinked == 5
    assert status.corpus_in_sync is True
    assert status.cases_in_sync is True


def test_ac9_editing_a_document_reembeds_only_that_chunk(kenv: KEnv) -> None:
    kenv.build()
    write_file(kenv.mini_k, "kb-a.md", replace_once(KB_A, "Đoạn mở đầu.", "Đoạn mở đầu mới."))
    assert kenv.status().corpus_in_sync is False
    result = kenv.build()
    assert result.embedded == 1
    assert result.cache_hits == 4
    text = kenv.one("MATCH (c:Chunk {chunk_id: 'KB-TYP-901#001'}) RETURN c.text")
    assert text == "Đoạn mở đầu mới."


def test_ac9_adding_and_removing_a_document_sweeps_its_nodes(kenv: KEnv) -> None:
    kenv.build()
    write_file(kenv.mini_k, "kb-c.md", KB_C)
    kenv.build()
    counts = kenv.counts()
    assert (counts["Document"], counts["Chunk"], counts["MENTIONS"]) == (3, 6, 6)

    (kenv.mini_k / "kb-c.md").unlink()
    kenv.build()
    counts = kenv.counts()
    assert (counts["Document"], counts["Chunk"], counts["MENTIONS"]) == (2, 5, 5)
    left = kenv.one("MATCH (c:Chunk {doc_id: 'KB-RFC-901'}) RETURN count(c)")
    assert left == 0


def test_ac9_a_new_case_run_makes_cases_out_of_sync(kenv: KEnv) -> None:
    kenv.build()
    run_cases(kenv.duck, kenv.settings)
    assert kenv.status().cases_in_sync is False


def test_ac9_changed_dimensions_need_full(kenv: KEnv) -> None:
    kenv.build()
    settings32 = k_neo_settings(kenv.mini_k, kenv.cache, AML__ASSISTANT__EMBEDDING__DIMENSIONS="32")
    fake32 = llm().FakeLLM(dim=32)  # not cached: the cache key does not include the dimension
    build = kbuild().build_knowledge
    with pytest.raises(kmodel().KnowledgeError) as error:
        build(kenv.duck, settings32, fake32)
    assert (
        "vector index chunk_embedding has 64 dimensions but assistant.embedding.dimensions is 32: "
        "run aml rag build --full"
    ) in str(error.value)

    result = build(kenv.duck, settings32, fake32, full=True)
    assert result.build_id == 1
    sizes = {r[0] for r in kenv.rows("MATCH (c:Chunk) RETURN size(c.embedding)")}
    assert sizes == {32}


def test_ac9_wrong_vector_length_fails_before_anything_is_written(kenv: KEnv) -> None:
    settings32 = k_neo_settings(kenv.mini_k, kenv.cache, AML__ASSISTANT__EMBEDDING__DIMENSIONS="32")
    kbuild().build_knowledge(kenv.duck, settings32, llm().FakeLLM(dim=32), full=True)
    before = kenv.counts()
    with pytest.raises(kmodel().KnowledgeError, match="embedding has 16 dimensions, expected 32"):
        kbuild().build_knowledge(kenv.duck, settings32, llm().FakeLLM(dim=16))
    assert kenv.counts() == before


def test_ac9_synced_customers_get_about_links_and_wipes_leave_6a_alone(kenv: KEnv) -> None:
    kenv.build()
    refresh_acct_edge_daily(kenv.duck)
    run_sync(kenv.duck, kenv.settings, full=True)
    customers = kenv.one("MATCH (c:Customer) RETURN count(c)")
    assert customers == 5
    accounts = kenv.one("MATCH (a:Account) RETURN count(a)")
    transfers = kenv.one("MATCH ()-[r:TRANSFERRED_TO]->() RETURN count(r)")

    result = kenv.build()
    assert result.cases_unlinked == 0
    assert kenv.one("MATCH ()-[r:ABOUT]->() RETURN count(r)") == 5
    linked = kenv.rows(
        "MATCH (c:Case)-[:ABOUT]->(u:Customer) "
        f"WHERE c.case_id IN ['{CASE_C01_A}', '{CASE_C01_B}'] RETURN u.golden_customer_id"
    )
    assert linked == [("G-C01",), ("G-C01",)]
    assert kenv.one("MATCH (c:Customer) RETURN count(c)") == customers
    assert kenv.one("MATCH (a:Account) RETURN count(a)") == accounts
    assert kenv.one("MATCH ()-[r:TRANSFERRED_TO]->() RETURN count(r)") == transfers

    client().run_write_file(kenv.driver, kenv.settings, "sync/wipe.cypher")
    counts = kenv.counts()
    assert (counts["Chunk"], counts["Case"], counts["ABOUT"]) == (5, 5, 0)
    assert kenv.one("MATCH (c:Customer) RETURN count(c)") == 0

    client().run_write_file(kenv.driver, kenv.settings, "knowledge/wipe.cypher")
    counts = kenv.counts()
    assert all(counts[label] == 0 for label in LABELS)
    names = {r[0] for r in kenv.rows("SHOW INDEXES YIELD name RETURN name")}
    assert "chunk_embedding" not in names
    constraints = {r[0] for r in kenv.rows("SHOW CONSTRAINTS YIELD name RETURN name")}
    assert constraints == CONSTRAINTS
