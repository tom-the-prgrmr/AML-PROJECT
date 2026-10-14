"""AC7 for specs/assistant-knowledge.md: the eight synthetic documents in docs/knowledge/."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import PROJECT_ROOT, get_settings, load_settings
from aml.common.db import DuckDb
from tests.cases.helpers import cli, mod

from .kn_helpers import OFFLINE_OLLAMA, OFFLINE_URI, kdocs, kmatches, kmodel

KNOWLEDGE_DIR = PROJECT_ROOT / "docs" / "knowledge"
FILES = [
    "typology-structuring.md",
    "typology-rapid-movement.md",
    "typology-mule-ring.md",
    "typology-round-tripping.md",
    "typology-sanctions-pep.md",
    "sop-investigation.md",
    "red-flag-checklist.md",
    "policy-aml-internal.md",
]
DOC_IDS = [
    "KB-POL-001",
    "KB-RFC-001",
    "KB-SOP-001",
    "KB-TYP-001",
    "KB-TYP-002",
    "KB-TYP-003",
    "KB-TYP-004",
    "KB-TYP-005",
]
RULE_WORDS = {
    "KB-TYP-001": ("STRUCTURING", "thresholds.large_cash_vnd"),
    "KB-TYP-002": ("RAPID_MOVEMENT",),
    "KB-TYP-003": ("FAN_IN", "FAN_OUT", "NET_SHARED_ATTRIBUTE", "NET_HUB"),
    "KB-TYP-004": ("NET_CYCLE",),
    "KB-TYP-005": ("SCREENING_ALERT", "SCREENING_REVIEW"),
}


@pytest.fixture(scope="module")
def corpus() -> Any:
    settings = load_settings(environ={})
    return kdocs().load_corpus(
        settings.path("docs/knowledge"), max_chars=settings.assistant.knowledge.chunk_max_chars
    )


def _text_of(corpus: Any, doc_id: str) -> str:
    return "\n".join(c.text for c in corpus.chunks if c.doc_id == doc_id)


def test_ac7_directory_holds_exactly_the_eight_files() -> None:
    assert sorted(p.name for p in KNOWLEDGE_DIR.glob("*.md")) == sorted(FILES)


def test_ac7_documents_and_metadata(corpus: Any) -> None:
    assert [d.doc_id for d in corpus.docs] == DOC_IDS
    for doc in corpus.docs:
        assert doc.language == "vi"
        assert doc.version == "1.0"
        assert doc.effective_date == date(2026, 1, 1)


def test_ac7_entity_counts_and_ids(corpus: Any) -> None:
    k = kmodel()
    by_label: dict[str, set[str]] = {}
    for e in corpus.entities:
        by_label.setdefault(e.label, set()).add(e.id)
    assert {label: len(ids) for label, ids in by_label.items()} == {
        "Typology": 6,
        "RedFlag": 18,
        "Procedure": 6,
        "Regulation": 3,
    }
    assert by_label["Typology"] == set(k.TYPOLOGY_IDS)
    assert by_label["RedFlag"] == {f"RF-{n:03d}" for n in range(1, 19)}
    assert by_label["Procedure"] == {f"PROC-{n:03d}" for n in range(1, 7)}
    assert by_label["Regulation"] == {f"REG-{n:03d}" for n in range(1, 4)}


def test_ac7_rule_typology_mapping_covers_every_typology() -> None:
    k = kmodel()
    mapped = set(kmatches().rule_typologies().values()) | set(k.SCREENING_LIST_TYPOLOGY.values())
    assert mapped == set(k.TYPOLOGY_IDS)


def test_ac7_every_typology_and_procedure_has_its_relations(corpus: Any) -> None:
    sources = Counter((r.type, r.source) for r in corpus.relations)
    for typology in kmodel().TYPOLOGY_IDS:
        assert sources[("HAS_RED_FLAG", typology)] >= 2, typology
        assert sources[("INVESTIGATED_BY", typology)] >= 1, typology
        assert sources[("GOVERNED_BY", typology)] >= 1, typology
    for entity in corpus.entities:
        if entity.label == "Procedure":
            assert sources[("REQUIRED_BY", entity.id)] >= 1, entity.id


def test_ac7_chunk_sizes_and_synthetic_marker(corpus: Any) -> None:
    for doc_id in DOC_IDS:
        chunks = [c for c in corpus.chunks if c.doc_id == doc_id]
        assert len(chunks) >= 3, doc_id
        first = next(c for c in chunks if c.seq == 1)
        assert "Tài liệu tổng hợp (synthetic)" in first.text, doc_id
    assert len(corpus.chunks) >= 30
    assert all(1 <= len(c.text) <= 1200 for c in corpus.chunks)


def test_ac7_documents_name_their_rules_and_config_keys(corpus: Any) -> None:
    for doc_id, words in RULE_WORDS.items():
        text = _text_of(corpus, doc_id)
        for word in words:
            assert word in text, (doc_id, word)


def test_ac7_documents_do_not_copy_threshold_values(corpus: Any) -> None:
    assert not any("400000000" in c.text for c in corpus.chunks)


def test_ac7_checklist_mentions_all_eighteen_red_flags(corpus: Any) -> None:
    mentioned = {m for c in corpus.chunks if c.doc_id == "KB-RFC-001" for m in c.mentions}
    assert {f"RF-{n:03d}" for n in range(1, 19)} <= mentioned


@pytest.fixture
def offline_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    db_path = tmp_path / "dry.duckdb"
    with DuckDb(db_path) as db:
        mod("aml.dba.schema").apply_schema(db)
    for key, value in {
        "DB_BACKEND": "duckdb",
        "AML__DB__DUCKDB_PATH": str(db_path),
        "AML__NEO4J__URI": OFFLINE_URI,
        "AML__OLLAMA__HOST": OFFLINE_OLLAMA,
        "AML__ASSISTANT__CACHE__DIR": str(tmp_path / "cache"),
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_ac7_dry_run_prints_the_counts_and_writes_nothing(corpus: Any, offline_cli: Path) -> None:
    result = cli("rag", "build", "--dry-run")
    assert result.exit_code == 0, result.output
    assert result.stdout.isascii()
    lines = [
        ln for ln in result.stdout.splitlines() if ln.startswith("dry_run documents=8 chunks=")
    ]
    assert len(lines) == 1
    line = lines[0]
    assert "typologies=6 red_flags=18 procedures=6 regulations=3" in line
    assert f"chunks={len(corpus.chunks)} " in line
    with DuckDb(offline_cli / "dry.duckdb") as db:
        assert int(db.query_df("SELECT COUNT(*) FROM audit_log").iloc[0, 0]) == 0
    assert not [p for p in (offline_cli / "cache").rglob("*") if p.is_file()]


def test_ac7_dry_run_on_an_empty_directory_fails(
    offline_cli: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = offline_cli / "empty"
    empty.mkdir()
    monkeypatch.setenv("AML__ASSISTANT__KNOWLEDGE__DIR", str(empty))
    get_settings.cache_clear()
    result = cli("rag", "build", "--dry-run")
    assert result.exit_code == 1, result.output
    assert "no knowledge documents in" in result.stderr
