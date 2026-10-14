"""Constants and value objects of the knowledge layer (pure Python, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

KNOWLEDGE_VERSION = "knowledge/v1"
VECTOR_INDEX = "chunk_embedding"
ENTITY_KEYS = {
    "Typology": "typology_id",
    "RedFlag": "red_flag_id",
    "Procedure": "procedure_id",
    "Regulation": "regulation_id",
}
ID_PATTERNS = {
    "Typology": r"[a-z][a-z0-9_]{2,39}",
    "RedFlag": r"RF-\d{3}",
    "Procedure": r"PROC-\d{3}",
    "Regulation": r"REG-\d{3}",
}
RELATIONS = {  # relation type -> (source label, target label); there is no other type
    "HAS_RED_FLAG": ("Typology", "RedFlag"),
    "INVESTIGATED_BY": ("Typology", "Procedure"),
    "GOVERNED_BY": ("Typology", "Regulation"),
    "REQUIRED_BY": ("Procedure", "Regulation"),
}
DOC_TYPES = ("TYPOLOGY", "SOP", "CHECKLIST", "POLICY")
DOC_ID_PATTERN = r"KB-[A-Z]{2,4}-\d{3}"
CHUNK_ID_PATTERN = r"KB-[A-Z]{2,4}-\d{3}#\d{3}"
TYPOLOGY_IDS = (
    "structuring",
    "rapid_movement",
    "mule_ring",
    "round_tripping",
    "sanctions_hit",
    "pep_hit",
)
SCREENING_LIST_TYPOLOGY = {"SANCTIONS": "sanctions_hit", "PEP": "pep_hit"}


class KnowledgeError(RuntimeError):
    """The knowledge documents or the knowledge layer are not valid."""


@dataclass(frozen=True)
class Entity:
    label: str
    id: str
    name: str
    doc_id: str  # the document that defines it


@dataclass(frozen=True)
class Relation:
    type: str
    source: str  # entity id
    target: str


@dataclass(frozen=True)
class KnowledgeDoc:
    doc_id: str  # the doc number, e.g. "KB-TYP-001"
    title: str
    doc_type: str
    version: str
    effective_date: date
    language: str  # "vi" | "en"
    source_file: str  # file name
    sha256: str  # of the whole file


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # f"{doc_id}#{seq:03d}", seq starts at 1 within each document
    doc_id: str
    seq: int
    heading: str
    text: str
    mentions: tuple[str, ...]  # entity ids, ascending


@dataclass(frozen=True)
class Corpus:
    docs: tuple[KnowledgeDoc, ...]  # by doc_id
    chunks: tuple[Chunk, ...]  # by (doc_id, seq)
    entities: tuple[Entity, ...]  # by (label, id)
    relations: tuple[Relation, ...]  # by (type, source, target)
    sha256: str  # of the sorted list of (doc_id, sha256)
