"""Application-level read-only guard for Cypher (pure Python, no driver import).

Neo4j Community has no RBAC. The real protection is the READ session of the server; this guard
refuses write clauses early, with a reason that can be audited. It is fail-closed and is not a
parser: strings, backtick identifiers and comments are blanked, then the rest is scanned for
whole-word write keywords and for ``CALL <procedure>`` outside the allow-list.

``guard/v2`` (see specs/neo4j-gds.md): a procedure name that matched the allow-list is removed
before the keyword scan (``gds.graph.drop`` holds the word DROP), and every ``gds.graph.<x>(`` --
after ``CALL`` or used as a function -- has to match the allow-list. Backtick quoting cannot hide
a name: a quoted procedure name after ``CALL`` is refused, and the ``gds.graph`` check also runs
on the text with the backticks removed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from fnmatch import fnmatchcase

WRITE_KEYWORDS: tuple[str, ...] = (
    "CREATE", "MERGE", "SET", "DELETE", "DETACH", "REMOVE", "DROP", "FOREACH",
    "LOAD", "ALTER", "RENAME", "GRANT", "DENY", "REVOKE", "TERMINATE",
)  # fmt: skip

_KEYWORD_RE = re.compile(r"\b(?:" + "|".join(WRITE_KEYWORDS) + r")\b", re.IGNORECASE)
_CALL_RE = re.compile(r"\bCALL\b\s*", re.IGNORECASE)
_PROCEDURE_RE = re.compile(r"[A-Za-z_][\w.]*")
_GDS_GRAPH_RE = re.compile(r"\bgds\s*\.\s*graph\s*\.\s*([A-Za-z_]\w*)\s*\(", re.IGNORECASE)

GUARD_VERSION = "guard/v2"


class GraphError(RuntimeError):
    """Any failure of the Neo4j projection layer."""


class WriteBlockedError(GraphError):
    """The query is not allowed on the read-only path."""


def _blank(cypher: str, *, unquote: bool = False) -> str:
    """Replace strings and comments with a space, and a backtick identifier with a lone backtick.

    The lone backtick keeps a quoted name from reading as "nothing" (``CALL `x`(`` is not a
    subquery). With ``unquote`` the identifier's own text is kept instead, without the backticks.
    """
    out: list[str] = []
    i, n = 0, len(cypher)
    while i < n:
        ch = cypher[i]
        if ch in "'\"`":
            start = i + 1
            i += 1
            while i < n and cypher[i] != ch:
                i += 2 if cypher[i] == "\\" and ch != "`" else 1
            if ch != "`":
                out.append(" ")
            else:
                out.append(cypher[start:i] if unquote else "`")
            i += 1
        elif cypher.startswith("//", i):
            end = cypher.find("\n", i)
            i = n if end < 0 else end
            out.append(" ")
        elif cypher.startswith("/*", i):
            end = cypher.find("*/", i + 2)
            i = n if end < 0 else end + 2
            out.append(" ")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


blank_literals = _blank  # public name for the Text2Cypher guard (same function, same behaviour)


def _blocked(message: str) -> WriteBlockedError:
    return WriteBlockedError(f"{message} is not allowed in a read-only query")


def assert_read_only(cypher: str, *, allowed_procedures: Sequence[str] = ()) -> None:
    """Raise ``WriteBlockedError`` unless ``cypher`` looks like a single read-only statement."""
    text = _blank(cypher)
    if not text.strip(" \t\r\n;"):
        raise WriteBlockedError("empty query")
    semicolon = text.find(";")
    if semicolon >= 0 and text[semicolon + 1 :].strip(" \t\r\n;"):
        raise WriteBlockedError("multiple statements are not allowed")
    patterns = [p.lower() for p in allowed_procedures]

    def allowed(name: str) -> bool:
        return any(fnmatchcase(name.lower(), p) for p in patterns)

    scanned = text
    for call in _CALL_RE.finditer(text):
        rest = text[call.end() :]
        if rest.startswith(("{", "(")):  # a subquery, its body is scanned for keywords below
            continue
        match = _PROCEDURE_RE.match(rest)
        name = match.group() if match else "<unknown>"
        if not match or not allowed(name):
            raise _blocked(f"procedure {name}")
        start = call.end() + match.start()  # an allowed name is not a keyword: blank it
        scanned = scanned[:start] + " " * len(name) + scanned[start + len(name) :]
    # gds.graph.* used as a function too, and with any part of the name in backticks
    for candidate in (text, _blank(cypher, unquote=True)):
        for graph_call in _GDS_GRAPH_RE.finditer(candidate):
            name = f"gds.graph.{graph_call.group(1)}"
            if not allowed(name):
                raise _blocked(f"procedure {name}")
    keyword = _KEYWORD_RE.search(scanned)
    if keyword:
        raise _blocked(f"write clause {keyword.group().upper()}")
