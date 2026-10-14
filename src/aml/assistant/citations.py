"""From 8b's ``kind:id`` citations to the citation contract of the UI (pure).

This is the ONE place where an evidence item becomes a `Citation`. An item gives one citation, named
after its FIRST ``kind:id`` (the subject of the item): ``txn`` -> ``transaction``, ``chunk`` ->
``chunk``, ``alert`` -> ``alert``, every other kind of 8b -> ``node``. An item without any citation
(a Text2Cypher row with no id) gives none.

The ids a reader can check are ``Citation.id`` and ``Citation.txn_ids``. ``node_ids`` only tell the
graph view what to highlight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aml.assistant.evidence import parse_citation

if TYPE_CHECKING:
    from aml.assistant.evidence import Evidence

KINDS = ("node", "transaction", "chunk", "alert")
KIND_MAP = {"txn": "transaction", "chunk": "chunk", "alert": "alert"}  # anything else -> "node"
CITATION_RE = re.compile(r"\[(\d+)\]")
_TRAILING = re.compile(r"(?:\s*\[\d+\])+$")
_NODE_KINDS = ("account", "customer")
_EXCERPT_FIELD = "chunk_text"


@dataclass(frozen=True)
class Citation:
    n: int
    kind: str  # one of KINDS
    id: str  # bare id of the FIRST citation of the evidence item
    label: str  # "<kind> <id>"
    node_ids: tuple[str, ...]  # graph highlight only
    txn_ids: tuple[str, ...]
    excerpt: str | None  # chunk text of a knowledge passage


def primary(evidence: Evidence) -> tuple[str, str] | None:
    """(Citation.kind, id) of the item's first citation; None when it has no citation."""
    if not evidence.citations:
        return None
    kind, id_ = parse_citation(evidence.citations[0])
    return KIND_MAP.get(kind, "node"), id_


def _ids(evidence: Evidence, kinds: tuple[str, ...]) -> tuple[str, ...]:
    pairs = (parse_citation(c) for c in evidence.citations)
    return tuple(dict.fromkeys(id_ for kind, id_ in pairs if kind in kinds))


def to_citation(evidence: Evidence, n: int) -> Citation:
    found = primary(evidence)
    if found is None:
        raise ValueError(f"evidence {evidence.ref} has no citation")
    kind, id_ = found
    excerpt = None
    if kind == "chunk":
        excerpt = next((u.text for u in evidence.untrusted if u.field == _EXCERPT_FIELD), None)
    return Citation(
        n=n,
        kind=kind,
        id=id_,
        label=f"{kind} {id_}",
        node_ids=_ids(evidence, _NODE_KINDS),
        txn_ids=_ids(evidence, ("txn",)),
        excerpt=excerpt,
    )


def join_citations(sentence: str, numbers: tuple[int, ...]) -> str:
    """``<sentence> [n][m]``; the sentence alone when it cites nothing."""
    if not numbers:
        return sentence
    return sentence + " " + "".join(f"[{n}]" for n in numbers)


def split_citations(line: str) -> tuple[str, tuple[int, ...]]:
    """The inverse of `join_citations`: (sentence, citation numbers)."""
    match = _TRAILING.search(line)
    if match is None:
        return line, ()
    numbers = tuple(int(n) for n in CITATION_RE.findall(match.group(0)))
    return line[: match.start()], numbers
