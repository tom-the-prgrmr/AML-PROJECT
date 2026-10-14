"""AC5 and AC6 for specs/assistant-knowledge.md: `load_corpus`, `split_section`, `embed_text`."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from .kn_helpers import (
    KB_A,
    KB_B,
    kdocs,
    kmodel,
    replace_once,
    sha256_of,
    write_file,
    write_mini_k,
)

MAX = 1200


@pytest.fixture
def mini_k(tmp_path: Path) -> Path:
    return write_mini_k(tmp_path / "kb")


def _load(directory: Path) -> Any:
    return kdocs().load_corpus(directory, max_chars=MAX)


def _chunk(corpus: Any, chunk_id: str) -> Any:
    return next(c for c in corpus.chunks if c.chunk_id == chunk_id)


# ---------------------------------------------------------------- AC5
def test_ac5_documents(mini_k: Path) -> None:
    corpus = _load(mini_k)
    assert [d.doc_id for d in corpus.docs] == ["KB-SOP-901", "KB-TYP-901"]
    doc = next(d for d in corpus.docs if d.doc_id == "KB-TYP-901")
    assert doc.title == "Structuring thử nghiệm"
    assert doc.doc_type == "TYPOLOGY"
    assert doc.version == "1.0"
    assert doc.effective_date == date(2026, 1, 1)
    assert doc.language == "vi"
    assert doc.source_file == "kb-a.md"
    assert doc.sha256 == sha256_of(mini_k / "kb-a.md")


def test_ac5_chunks_ids_headings_text_and_mentions(mini_k: Path) -> None:
    corpus = _load(mini_k)
    assert [c.chunk_id for c in corpus.chunks] == [
        "KB-SOP-901#001",
        "KB-SOP-901#002",
        "KB-TYP-901#001",
        "KB-TYP-901#002",
        "KB-TYP-901#003",
    ]
    expected = {
        "KB-TYP-901#001": ("Structuring thử nghiệm", "Đoạn mở đầu.", ()),
        "KB-TYP-901#002": ("Mô tả", "Khách hàng chia nhỏ tiền mặt.", ("structuring",)),
        "KB-TYP-901#003": (
            "Dấu hiệu",
            "Nộp tiền nhiều lần dưới ngưỡng.",
            ("RF-901", "structuring"),
        ),
        "KB-SOP-901#001": ("Bước 1", "Yêu cầu chứng từ nguồn tiền.", ("PROC-901",)),
        "KB-SOP-901#002": ("Căn cứ", "Theo quy định nội bộ.", ("REG-901",)),
    }
    for chunk_id, (heading, text, mentions) in expected.items():
        chunk = _chunk(corpus, chunk_id)
        assert (chunk.heading, chunk.text, chunk.mentions) == (heading, text, mentions), chunk_id
    assert not any("{" in c.heading for c in corpus.chunks)


def test_ac5_entities_and_relations(mini_k: Path) -> None:
    corpus = _load(mini_k)
    assert [(e.label, e.id) for e in corpus.entities] == [
        ("Procedure", "PROC-901"),
        ("RedFlag", "RF-901"),
        ("Regulation", "REG-901"),
        ("Typology", "structuring"),
    ]
    red_flag = next(e for e in corpus.entities if e.id == "RF-901")
    assert red_flag.name == "Nộp tiền mặt sát ngưỡng"
    assert red_flag.doc_id == "KB-TYP-901"
    assert [(r.type, r.source, r.target) for r in corpus.relations] == [
        ("HAS_RED_FLAG", "structuring", "RF-901"),
        ("INVESTIGATED_BY", "structuring", "PROC-901"),
        ("REQUIRED_BY", "PROC-901", "REG-901"),
    ]


def test_ac5_embed_text(mini_k: Path) -> None:
    corpus = _load(mini_k)
    doc = next(d for d in corpus.docs if d.doc_id == "KB-TYP-901")
    chunk = _chunk(corpus, "KB-TYP-901#003")
    assert (
        kdocs().embed_text(doc, chunk)
        == "Structuring thử nghiệm — Dấu hiệu\nNộp tiền nhiều lần dưới ngưỡng."
    )


def test_ac5_load_is_deterministic_and_sha_follows_content(mini_k: Path) -> None:
    first = _load(mini_k)
    assert _load(mini_k) == first
    write_file(mini_k, "kb-b.md", replace_once(KB_B, "Theo quy định", "Theo Quy định"))
    assert _load(mini_k).sha256 != first.sha256


def test_ac5_split_section() -> None:
    split_section = kdocs().split_section
    assert split_section(["a" * 40, "b" * 40, "c" * 40], 100) == [
        "a" * 40 + "\n\n" + "b" * 40,
        "c" * 40,
    ]
    assert split_section(["x" * 250], 100) == ["x" * 100, "x" * 100, "x" * 50]
    assert split_section([], 100) == []


def test_ac5_long_section_is_split_into_chunks(mini_k: Path) -> None:
    long_section = "\n## Dài {structuring}\n\n" + "\n\n".join(c * 500 for c in "abc") + "\n"
    write_file(mini_k, "kb-a.md", KB_A + long_section)
    corpus = _load(mini_k)
    typ = [c for c in corpus.chunks if c.doc_id == "KB-TYP-901"]
    assert len(typ) == 5
    for chunk in typ[3:]:
        assert chunk.heading == "Dài"
        assert chunk.mentions == ("structuring",)
    assert [len(c.text) for c in typ[3:]] == [1002, 500]
    assert [c.chunk_id for c in typ[3:]] == ["KB-TYP-901#004", "KB-TYP-901#005"]


# ---------------------------------------------------------------- AC6
def _drop_line(text: str, line: str) -> str:
    return replace_once(text, line + "\n", "")


CASES: dict[str, tuple[str, Callable[[str], str] | None, str]] = {
    "missing_effective_date": (
        "kb-a.md",
        lambda t: _drop_line(t, "effective_date: 2026-01-01"),
        "missing metadata 'effective_date'",
    ),
    "no_frontmatter": (
        "kb-a.md",
        lambda t: t.split("---\n", 2)[2],
        "missing metadata 'doc_number'",
    ),
    "bad_doc_number": (
        "kb-a.md",
        lambda t: replace_once(t, "doc_number: KB-TYP-901", "doc_number: TYP-1"),
        "invalid doc_number",
    ),
    "duplicate_doc_number": (
        "kb-b.md",
        lambda t: replace_once(t, "doc_number: KB-SOP-901", "doc_number: KB-TYP-901"),
        "duplicate doc_number KB-TYP-901",
    ),
    "unknown_doc_type": (
        "kb-a.md",
        lambda t: replace_once(t, "doc_type: TYPOLOGY", "doc_type: MEMO"),
        "unknown doc_type",
    ),
    "invalid_date": (
        "kb-a.md",
        lambda t: replace_once(t, "effective_date: 2026-01-01", "effective_date: 2026-13-01"),
        "invalid effective_date",
    ),
    "unknown_label": (
        "kb-a.md",
        lambda t: replace_once(
            t, "relations:", "  - {label: Person, id: P-001, name: x}\nrelations:"
        ),
        "unknown label 'Person'",
    ),
    "invalid_id_for_label": (
        "kb-a.md",
        lambda t: replace_once(t, "id: RF-901,", "id: RF-1,"),
        "invalid id 'RF-1' for RedFlag",
    ),
    "defined_twice": (
        "kb-b.md",
        lambda t: replace_once(
            t, "relations:", "  - {label: RedFlag, id: RF-901, name: y}\nrelations:"
        ),
        "entity RF-901 is defined twice",
    ),
    "unknown_relation_type": (
        "kb-a.md",
        lambda t: replace_once(
            t, "---\n#", "  - {from: structuring, type: CAUSES, to: RF-901}\n---\n#"
        ),
        "unknown relation type 'CAUSES'",
    ),
    "wrong_label_pair": (
        "kb-a.md",
        lambda t: replace_once(
            t, "---\n#", "  - {from: RF-901, type: HAS_RED_FLAG, to: structuring}\n---\n#"
        ),
        "relation HAS_RED_FLAG must go from Typology to RedFlag",
    ),
    "unknown_relation_target": (
        "kb-a.md",
        lambda t: replace_once(
            t, "---\n#", "  - {from: structuring, type: HAS_RED_FLAG, to: RF-999}\n---\n#"
        ),
        "unknown entity 'RF-999'",
    ),
    "unknown_entity_in_heading": (
        "kb-a.md",
        lambda t: replace_once(t, "## Mô tả {structuring}", "## Mô tả {structuring RF-777}"),
        "unknown entity 'RF-777'",
    ),
    "relation_to_a_missing_file": (
        "kb-a.md",
        None,
        "unknown entity 'PROC-901'",
    ),
    "never_mentioned": (
        "kb-b.md",
        lambda t: replace_once(t, "## Căn cứ {REG-901}", "## Căn cứ"),
        "entity REG-901 is never mentioned",
    ),
    "no_content": (
        "kb-b.md",
        lambda t: t.split("defines:")[0] + "---\n# SOP thử nghiệm\n",
        "no content",
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_ac6_invalid_corpus_raises_knowledge_error(name: str, mini_k: Path) -> None:
    file_name, edit, expected = CASES[name]
    if edit is None:  # the file is removed instead of edited
        (mini_k / "kb-b.md").unlink()
    else:
        path = mini_k / file_name
        write_file(mini_k, file_name, edit(path.read_text(encoding="utf-8")))
    with pytest.raises(kmodel().KnowledgeError) as error:
        _load(mini_k)
    message = str(error.value)
    assert file_name in message
    assert expected in message


def test_ac6_empty_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(kmodel().KnowledgeError, match="no knowledge documents in"):
        _load(empty)


def test_ac6_copy_of_the_valid_corpus_loads(mini_k: Path, tmp_path: Path) -> None:
    """Guard for the table above: the unedited MINI-K is valid."""
    copy = tmp_path / "copy"
    shutil.copytree(mini_k, copy)
    assert len(_load(copy).docs) == 2
