"""Application-level read-only guard for Cypher (pure Python, no driver import).

Neo4j Community has no RBAC. The real protection is the READ session of the server; this guard
refuses write clauses early, with a reason that can be audited. It is fail-closed and is not a
parser: strings, backtick identifiers and comments are blanked, then the rest is scanned for
whole-word write keywords and for ``CALL <procedure>`` outside the allow-list.
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


class GraphError(RuntimeError):
    """Any failure of the Neo4j projection layer."""


class WriteBlockedError(GraphError):
    """The query is not allowed on the read-only path."""


def _blank(cypher: str) -> str:
    """Replace strings, backtick identifiers and comments with a single space each."""
    out: list[str] = []
    i, n = 0, len(cypher)
    while i < n:
        ch = cypher[i]
        if ch in "'\"`":
            i += 1
            while i < n and cypher[i] != ch:
                i += 2 if cypher[i] == "\\" and ch != "`" else 1
            i += 1
            out.append(" ")
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
    for call in _CALL_RE.finditer(text):
        rest = text[call.end() :]
        if rest.startswith(("{", "(")):  # a subquery, its body is scanned for keywords below
            continue
        match = _PROCEDURE_RE.match(rest)
        name = match.group() if match else "<unknown>"
        if not match or not any(fnmatchcase(name.lower(), p) for p in patterns):
            raise _blocked(f"procedure {name}")
    keyword = _KEYWORD_RE.search(text)
    if keyword:
        raise _blocked(f"write clause {keyword.group().upper()}")
