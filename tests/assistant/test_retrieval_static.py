"""AC1 for specs/assistant-retrievers.md: config, constants, Cypher files, source boundaries."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from aml.common.config import PROJECT_ROOT, load_settings
from tests.neo4j_sync.helpers import READ_PROCEDURES

from .rt_helpers import adapter_mod, ev_mod, guard_mod, mod, route_mod

ASSISTANT_SRC = PROJECT_ROOT / "src" / "aml" / "assistant"
RETRIEVAL_FILES = {
    "customer.cypher",
    "transfer_totals.cypher",
    "transfers.cypher",
    "shared.cypher",
    "typologies.cypher",
    "typology_chunks.cypher",
    "expand_chunks.cypher",
}
LABELS = {
    "Customer",
    "Account",
    "Device",
    "Phone",
    "Address",
    "Case",
    "Typology",
    "RedFlag",
    "Procedure",
    "Regulation",
}
RELATIONSHIPS = {
    "OWNS",
    "USES_DEVICE",
    "HAS_PHONE",
    "LIVES_AT",
    "TRANSFERRED_TO",
    "SENT_TO",
    "ABOUT",
    "MATCHES_TYPOLOGY",
    "HAS_RED_FLAG",
    "INVESTIGATED_BY",
    "GOVERNED_BY",
    "REQUIRED_BY",
}


def _source(name: str) -> str:
    return (ASSISTANT_SRC / name).read_text(encoding="utf-8")


def test_ac1_retrieval_config_defaults() -> None:
    r = load_settings(environ={}).assistant.retrieval
    assert r.hops == 2
    assert r.max_transfers == 8
    assert r.max_shared == 5
    assert r.include_memos is True
    assert r.max_untrusted_chars == 300
    assert r.max_chunk_chars == 1200
    assert r.top_k == 3
    assert r.min_score == 0.0
    assert r.max_linked_per_chunk == 3
    assert r.max_typology_chunks == 1
    assert r.max_context_chars == 4500


def test_ac1_text2cypher_config_defaults() -> None:
    t = load_settings(environ={}).assistant.text2cypher
    assert t.enabled is True
    assert t.max_rows == 10
    assert t.timeout_seconds == 10
    assert t.max_path_length == 3
    assert t.max_query_chars == 2000
    assert t.max_attempts == 2


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("AML__ASSISTANT__RETRIEVAL__HOPS", "4", "hops must be between 1 and 3"),
        ("AML__ASSISTANT__TEXT2CYPHER__MAX_ROWS", "0", "max_rows must be between 1 and 200"),
        ("AML__ASSISTANT__TEXT2CYPHER__TIMEOUT_SECONDS", "0", "timeout_seconds must be > 0"),
        (
            "AML__ASSISTANT__TEXT2CYPHER__MAX_PATH_LENGTH",
            "6",
            "max_path_length must be between 1 and 5",
        ),
        (
            "AML__ASSISTANT__RETRIEVAL__MAX_CONTEXT_CHARS",
            "100",
            "max_context_chars must be between 500 and 100000",
        ),
    ],
)
def test_ac1_invalid_retrieval_config_is_rejected(key: str, value: str, message: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(message)):
        load_settings(environ={key: value})


def test_ac1_read_procedures_unchanged_and_no_vector_procedure() -> None:
    s = load_settings(environ={})
    assert s.neo4j.read_procedures == READ_PROCEDURES
    assert len(s.neo4j.read_procedures) == 7
    assert "db.index.vector.queryNodes" not in s.neo4j.read_procedures


def test_ac1_retrieval_cypher_files_are_single_read_only_statements() -> None:
    client = mod("aml.graph.neo4j.client")
    from aml.graph.neo4j.guard import assert_read_only

    directory = client.CYPHER_ROOT / "retrieval"
    assert {p.name for p in directory.iterdir()} == RETRIEVAL_FILES
    for name in sorted(RETRIEVAL_FILES):
        statements = client.load_statements(f"retrieval/{name}")
        assert len(statements) == 1, name
        statement = statements[0]
        assert_read_only(statement, allowed_procedures=())
        assert not re.search(r"\bCALL\b", statement, re.IGNORECASE), name
        assert "apoc." not in statement.lower(), name
        returned = re.split(r"\bRETURN\b", statement, flags=re.IGNORECASE)[-1]
        assert "embedding" not in returned.lower(), name


def test_ac1_expand_chunks_is_a_query_tail() -> None:
    client = mod("aml.graph.neo4j.client")
    (statement,) = client.load_statements("retrieval/expand_chunks.cypher")
    assert statement.startswith("WITH node, score")
    assert "MENTIONS" in statement
    assert "$min_score" in statement
    assert "$max_linked" in statement


def test_ac1_write_prefixes_gain_no_retrieval_entry_and_guard_version_is_kept() -> None:
    """The spec lists ("schema.cypher", "sync/"); 8a (approved) has since added "knowledge/"."""
    client = mod("aml.graph.neo4j.client")
    guard = mod("aml.graph.neo4j.guard")
    assert client.WRITE_PREFIXES == ("schema.cypher", "sync/", "knowledge/")
    assert guard.GUARD_VERSION == "guard/v2"
    with pytest.raises(guard.GraphError, match="is not a write file"):
        client.run_write_file(None, load_settings(environ={}), "retrieval/customer.cypher")


def test_ac1_guard_exposes_blank_literals() -> None:
    guard = mod("aml.graph.neo4j.guard")
    assert guard.blank_literals is guard._blank
    assert guard.blank_literals("RETURN 'a;b' // c") == guard._blank("RETURN 'a;b' // c")
    assert ";" not in guard.blank_literals("RETURN 'a;b'")


def test_ac1_graph_schema_contents() -> None:
    schema = mod("aml.assistant.schema").GRAPH_SCHEMA
    assert set(schema.labels) == LABELS
    assert set(schema.relationships) == RELATIONSHIPS
    for forbidden in ("embedding", "text", "build_id", "synced_run", "txn_watermark"):
        assert forbidden not in schema.properties
    for needed in ("txn_id", "amount", "ts", "evidence_ids", "typology_id"):
        assert needed in schema.properties


def test_ac1_schema_text_names_the_graph_and_hides_knowledge_chunks() -> None:
    text = mod("aml.assistant.schema").schema_text()
    for name in sorted(LABELS | RELATIONSHIPS):
        assert name in text, name
    assert "LOCAL DATETIME" in text
    assert "Chunk" not in text


def test_ac1_constants() -> None:
    e = ev_mod()
    assert e.CITATION_KINDS == (
        "case",
        "customer",
        "account",
        "txn",
        "alert",
        "chunk",
        "typology",
        "red_flag",
        "procedure",
        "regulation",
    )
    assert e.RETRIEVERS == (
        "case_graph",
        "txn_lookup",
        "vector",
        "graph_expansion",
        "text2cypher",
        "case_view",
    )
    assert route_mod().ROUTES == ("txn_lookup", "case_graph", "knowledge", "text2cypher")
    assert mod("aml.assistant.retrieve").MODES == ("graphrag", "vector")
    assert guard_mod().T2C_GUARD_VERSION == "t2c-guard/v1"


def test_ac1_pure_modules_import_no_driver_or_http_library() -> None:
    pattern = re.compile(r"^\s*(?:import|from)\s+(neo4j|ollama|requests|httpx|urllib)\b", re.M)
    for name in ("evidence.py", "schema.py", "cypher_guard.py", "router.py"):
        source = _source(name)
        assert pattern.findall(source) == [], name
        for banned in ("import neo4j", "ollama", "requests", "httpx", "urllib"):
            assert banned not in source, (name, banned)


def test_ac1_only_two_modules_touch_neo4j_graphrag() -> None:
    users = set()
    for path in ASSISTANT_SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "neo4j_graphrag" in text:
            users.add(path.name)
        for banned in ("Text2CypherRetriever", "neo4j_graphrag.llm", "neo4j_graphrag.generation"):
            assert banned not in text, (path.name, banned)
    assert users == {"graphrag_adapter.py", "knowledge_retriever.py"}


def test_ac1_pyproject_dependencies() -> None:
    data = tomllib.loads(Path(PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert [d for d in deps if d.startswith("neo4j-graphrag")] == ["neo4j-graphrag>=1.22,<2"]
    assert "neo4j>=6.3.1" in deps
    names = {re.split(r"[<>=!~\[\s;]", d, maxsplit=1)[0].lower() for d in deps}
    for hosted in ("openai", "ollama", "anthropic"):
        assert hosted not in names


def test_ac1_neo4j_graphrag_package_is_installed() -> None:
    import importlib.metadata

    import neo4j_graphrag  # noqa: F401  - a missing package must FAIL here, not skip

    assert importlib.metadata.version("neo4j-graphrag").startswith("1.")


def test_ac1_adapter_module_exists() -> None:
    assert adapter_mod().GuardedDriver is not None
