"""Read the knowledge documents of a directory: metadata, entities, relations and chunks.

Pure: it only reads files. Every problem is a `KnowledgeError` whose message starts with the file
name, so the author knows which document to fix (rules in specs/assistant-knowledge.md).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from aml.assistant.knowledge.model import (
    DOC_ID_PATTERN,
    DOC_TYPES,
    ID_PATTERNS,
    RELATIONS,
    Chunk,
    Corpus,
    Entity,
    KnowledgeDoc,
    KnowledgeError,
    Relation,
)

REQUIRED_KEYS = ("doc_number", "title", "doc_type", "version", "effective_date", "language")
LANGUAGES = ("vi", "en")
HEADING = re.compile(r"^##\s+(.*?)\s*(?:\{([^}]*)\})?\s*$")
BLANK_LINES = re.compile(r"\n\s*\n")
MENTION_SEPARATORS = re.compile(r"[\s,]+")
TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"


class _FrontmatterLoader(yaml.SafeLoader):
    """SafeLoader that leaves ISO dates as strings, so a bad date is our error, not YAML's."""


_FrontmatterLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != TIMESTAMP_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@dataclass
class _Parsed:
    """One document after reading, before the checks that need the whole directory."""

    doc: KnowledgeDoc
    entities: list[Entity]
    relations: list[tuple[str, str, str]]
    chunks: list[Chunk]
    file: str = field(init=False)

    def __post_init__(self) -> None:
        self.file = self.doc.source_file


def split_section(paragraphs: Sequence[str], max_chars: int) -> list[str]:
    """Pack paragraphs into texts of at most `max_chars`; a longer one is cut into equal parts."""
    texts: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                texts.append(current)
                current = ""
            texts.extend(
                paragraph[start : start + max_chars]
                for start in range(0, len(paragraph), max_chars)
            )
        elif not current:
            current = paragraph
        elif len(current) + 2 + len(paragraph) <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            texts.append(current)
            current = paragraph
    if current:
        texts.append(current)
    return texts


def embed_text(doc: KnowledgeDoc, chunk: Chunk) -> str:
    """The text that is embedded for a chunk: title and heading give the passage its context."""
    return f"{doc.title} — {chunk.heading}\n{chunk.text}"


def load_corpus(directory: Path, *, max_chars: int) -> Corpus:
    """Load every `*.md` file of `directory` (by file name) and cross-check the whole set."""
    files = sorted((p for p in directory.glob("*.md") if p.is_file()), key=lambda p: p.name)
    if not files:
        raise KnowledgeError(f"no knowledge documents in {directory}")
    parsed: list[_Parsed] = []
    seen_docs: set[str] = set()
    seen_entities: set[str] = set()
    for path in files:
        item = _read_document(path, max_chars)
        _check_unique(item, seen_docs, seen_entities)
        parsed.append(item)
    entities = {e.id: e for item in parsed for e in item.entities}
    relations = _check_relations(parsed, entities)
    _check_mentions(parsed, entities)
    docs = sorted((item.doc for item in parsed), key=lambda d: d.doc_id)
    digest = hashlib.sha256(
        json.dumps([[d.doc_id, d.sha256] for d in docs], separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return Corpus(
        docs=tuple(docs),
        chunks=tuple(sorted((c for item in parsed for c in item.chunks), key=_chunk_order)),
        entities=tuple(sorted(entities.values(), key=lambda e: (e.label, e.id))),
        relations=tuple(sorted(relations, key=lambda r: (r.type, r.source, r.target))),
        sha256=digest,
    )


def _chunk_order(chunk: Chunk) -> tuple[str, int]:
    return chunk.doc_id, chunk.seq


def _check_unique(item: _Parsed, seen_docs: set[str], seen_entities: set[str]) -> None:
    if item.doc.doc_id in seen_docs:
        raise KnowledgeError(f"{item.file}: duplicate doc_number {item.doc.doc_id}")
    seen_docs.add(item.doc.doc_id)
    for entity in item.entities:
        if entity.id in seen_entities:
            raise KnowledgeError(f"{item.file}: entity {entity.id} is defined twice")
        seen_entities.add(entity.id)


def _check_relations(parsed: list[_Parsed], entities: dict[str, Entity]) -> list[Relation]:
    relations: set[Relation] = set()
    for item in parsed:
        for rel_type, source, target in item.relations:
            for entity_id in (source, target):
                if entity_id not in entities:
                    raise KnowledgeError(f"{item.file}: unknown entity '{entity_id}'")
            want_source, want_target = RELATIONS[rel_type]
            if (entities[source].label, entities[target].label) != (want_source, want_target):
                raise KnowledgeError(
                    f"{item.file}: relation {rel_type} must go from {want_source} to {want_target}"
                )
            relations.add(Relation(rel_type, source, target))
    return list(relations)


def _check_mentions(parsed: list[_Parsed], entities: dict[str, Entity]) -> None:
    mentioned: set[str] = set()
    for item in parsed:
        for chunk in item.chunks:
            for entity_id in chunk.mentions:
                if entity_id not in entities:
                    raise KnowledgeError(f"{item.file}: unknown entity '{entity_id}'")
                mentioned.add(entity_id)
    for item in parsed:
        for entity in item.entities:
            if entity.id not in mentioned:
                raise KnowledgeError(f"{item.file}: entity {entity.id} is never mentioned")


def _read_document(path: Path, max_chars: int) -> _Parsed:
    raw = path.read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n")
    meta, body = _split_frontmatter(path.name, text)
    doc = _build_doc(path.name, meta, hashlib.sha256(raw).hexdigest())
    entities = _read_entities(path.name, doc.doc_id, meta.get("defines"))
    relations = _read_relations(path.name, meta.get("relations"))
    chunks = _read_chunks(doc, body, max_chars)
    if not chunks:
        raise KnowledgeError(f"{path.name}: no content")
    return _Parsed(doc, entities, relations, chunks)


def _split_frontmatter(name: str, text: str) -> tuple[dict[str, Any], str]:
    lines = text.split("\n")
    if lines[0] != "---":
        return {}, text
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise KnowledgeError(f"{name}: frontmatter is not closed by a '---' line") from None
    try:
        meta = yaml.load("\n".join(lines[1:end]), Loader=_FrontmatterLoader)
    except yaml.YAMLError as exc:
        raise KnowledgeError(f"{name}: invalid frontmatter ({exc})") from exc
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise KnowledgeError(f"{name}: invalid frontmatter (not a mapping)")
    return meta, "\n".join(lines[end + 1 :])


def _build_doc(name: str, meta: dict[str, Any], sha256: str) -> KnowledgeDoc:
    for key in REQUIRED_KEYS:
        if meta.get(key) in (None, ""):
            raise KnowledgeError(f"{name}: missing metadata '{key}'")
    doc_number, title, doc_type = meta["doc_number"], meta["title"], meta["doc_type"]
    if not isinstance(doc_number, str) or not re.fullmatch(DOC_ID_PATTERN, doc_number):
        raise KnowledgeError(f"{name}: invalid doc_number '{doc_number}'")
    if doc_type not in DOC_TYPES:
        raise KnowledgeError(f"{name}: unknown doc_type '{doc_type}'")
    try:
        effective = date.fromisoformat(str(meta["effective_date"]))
    except ValueError:
        raise KnowledgeError(f"{name}: invalid effective_date '{meta['effective_date']}'") from None
    if meta["language"] not in LANGUAGES:
        raise KnowledgeError(f"{name}: invalid language '{meta['language']}'")
    if not isinstance(meta["version"], str) or not isinstance(title, str):
        raise KnowledgeError(f"{name}: version and title must be strings")
    return KnowledgeDoc(
        doc_id=doc_number,
        title=title,
        doc_type=doc_type,
        version=meta["version"],
        effective_date=effective,
        language=meta["language"],
        source_file=name,
        sha256=sha256,
    )


def _list_of_mappings(name: str, key: str, value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise KnowledgeError(f"{name}: '{key}' must be a list of mappings")
    return value


def _read_entities(name: str, doc_id: str, value: Any) -> list[Entity]:
    entities: list[Entity] = []
    for row in _list_of_mappings(name, "defines", value):
        label, entity_id, entity_name = row.get("label"), row.get("id"), row.get("name")
        if label not in ID_PATTERNS:
            raise KnowledgeError(f"{name}: unknown label '{label}'")
        if not isinstance(entity_id, str) or not re.fullmatch(ID_PATTERNS[label], entity_id):
            raise KnowledgeError(f"{name}: invalid id '{entity_id}' for {label}")
        if not isinstance(entity_name, str) or not entity_name.strip():
            raise KnowledgeError(f"{name}: missing metadata 'name' of entity {entity_id}")
        entities.append(Entity(label, entity_id, entity_name.strip(), doc_id))
    return entities


def _read_relations(name: str, value: Any) -> list[tuple[str, str, str]]:
    relations: list[tuple[str, str, str]] = []
    for row in _list_of_mappings(name, "relations", value):
        rel_type = row.get("type")
        if rel_type not in RELATIONS:
            raise KnowledgeError(f"{name}: unknown relation type '{rel_type}'")
        relations.append((rel_type, str(row.get("from")), str(row.get("to"))))
    return relations


def _read_chunks(doc: KnowledgeDoc, body: str, max_chars: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, mentions, lines in _sections(doc.title, body):
        paragraphs = [p.strip() for p in BLANK_LINES.split("\n".join(lines))]
        for text in split_section([p for p in paragraphs if p], max_chars):
            seq = len(chunks) + 1
            chunks.append(
                Chunk(f"{doc.doc_id}#{seq:03d}", doc.doc_id, seq, heading, text, mentions)
            )
    return chunks


def _sections(title: str, body: str) -> list[tuple[str, tuple[str, ...], list[str]]]:
    """(heading, mentions, lines) per section; the part before the first `## ` uses the title."""
    sections: list[tuple[str, tuple[str, ...], list[str]]] = [(title, (), [])]
    for line in body.split("\n"):
        if line.startswith("## "):
            match = HEADING.match(line)
            heading = match.group(1) if match else line[3:].strip()
            ids = MENTION_SEPARATORS.split((match.group(2) or "").strip()) if match else []
            sections.append((heading, tuple(sorted({i for i in ids if i})), []))
        elif line.startswith("# "):
            continue
        else:
            sections[-1][2].append(line)
    return sections
