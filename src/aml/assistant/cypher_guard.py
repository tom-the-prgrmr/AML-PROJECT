"""Guardrail for generated Cypher (pure Python), on top of the read-only guard of the graph layer.

A small local model cannot be trusted to keep rules, so every rule is enforced here after the
query is generated. The guard is fail-closed and is not a parser: it accepts one ``MATCH ...
RETURN`` statement that only names labels, relationship types, properties and functions of
`GRAPH_SCHEMA`, and it forces a ``LIMIT``. Some valid queries are rejected (a map in ``RETURN``
with its own keys, an identifier equal to a keyword); the model gets one more attempt. The real
protection stays the READ session and the timeout of the server.

The checks run in a fixed order and the first one that fails names the rule.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

from aml.assistant.schema import GRAPH_SCHEMA, GraphSchema
from aml.graph.neo4j.guard import GraphError, WriteBlockedError, assert_read_only, blank_literals

T2C_GUARD_VERSION = "t2c-guard/v1"
RULES = (
    "empty",
    "too_long",
    "backtick",
    "comment",
    "guard",
    "clause",
    "parameter",
    "label",
    "property",
    "function",
    "path",
)
FORBIDDEN_CLAUSES = ("CALL", "UNION", "UNWIND", "SHOW", "EXPLAIN", "PROFILE", "USE")
DURATION_UNITS = frozenset({"years", "months", "weeks", "days", "hours", "minutes", "seconds"})
# words that may stand right before "(" without being a function call
KEYWORDS = frozenset(
    {
        "match", "optional", "where", "return", "with", "and", "or", "xor", "not", "in", "as",
        "by", "order", "limit", "skip", "distinct", "case", "when", "then", "else", "end", "is",
        "null", "asc", "desc", "starts", "ends", "contains",
    }
)  # fmt: skip
LITERALS = frozenset({"true", "false", "null"})

_NAME = r"[A-Za-z_]\w*"
_START_RE = re.compile(r"\s*(?:OPTIONAL\s+MATCH|MATCH)\b", re.IGNORECASE)
_RETURN_RE = re.compile(r"\bRETURN\b", re.IGNORECASE)
_PARAM_RE = re.compile(r"\$(\w*)")
_COLON_RE = re.compile(r":\s*(.?)")
_LABELS_RE = re.compile(rf"{_NAME}(?:\s*[|&:]+\s*{_NAME})*")
_IS_RE = re.compile(r"\bIS\b(?!\s+(?:NOT\s+)?NULL\b)", re.IGNORECASE)
_CALL_RE = re.compile(rf"(?<![\w.])({_NAME}(?:\s*\.\s*{_NAME})*)\s*\(")
_PROPERTY_RE = re.compile(rf"\.\s*({_NAME})\b(?!\s*\()")
_MAP_KEY_RE = re.compile(rf"[{{,]\s*({_NAME})\s*:")
_ALL_PROPERTIES_RE = re.compile(r"\.\s*\*")
_INDEX_RE = re.compile(r"\s*-?\d*\s*(?:\.\.\s*-?\d*\s*)?")
_LAST_WORD_RE = re.compile(r"(\w+)$")
_REL_RE = re.compile(r"-\s*\[([^\]]*)\]\s*-")
_STAR_RE = re.compile(r"\*\s*(\d*)\s*(\.\.)?\s*(\d*)")
_QUANTIFIER = r"\s*(?:[+*]|\{\s*\d*\s*(?:,\s*\d*\s*)?\})"
_QUANTIFIER_RE = re.compile(_QUANTIFIER)
_ARROW_RE = re.compile(r"-\s*\[|\]\s*-|->|<-|--")
# a quantified relationship: -[:T]->+ , -[:T]-{1,3} , -->*
_QUANTIFIED_REL_RE = re.compile(r"(?:\]\s*-\s*>?|->|--)" + _QUANTIFIER)
_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)$", re.IGNORECASE)


class CypherRejectedError(GraphError):
    """A generated query broke a rule of the Text2Cypher guard."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule  # one of RULES


@dataclass(frozen=True)
class ValidatedCypher:
    text: str  # the query that will run (LIMIT forced)
    limit: int
    original_limit: int | None


def _strings_blanked(cypher: str) -> str:
    """Blank quoted strings only; backticks and comment markers stay visible."""
    out: list[str] = []
    i, n = 0, len(cypher)
    while i < n:
        ch = cypher[i]
        if ch in "'\"":
            i += 1
            while i < n and cypher[i] != ch:
                i += 2 if cypher[i] == "\\" else 1
            out.append(" ")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _check_clauses(text: str) -> None:
    for word in FORBIDDEN_CLAUSES:
        if re.search(rf"\b{word}\b", text, re.IGNORECASE):
            raise CypherRejectedError("clause", f"clause {word} is not allowed")
    if not _START_RE.match(text):
        raise CypherRejectedError("clause", "query must start with MATCH")
    if not _RETURN_RE.search(text):
        raise CypherRejectedError("clause", "query has no RETURN clause")


def _check_parameters(text: str, allowed: Collection[str]) -> None:
    for match in _PARAM_RE.finditer(text):
        if not match.group(1):  # "$(" builds a label or a property name at run time
            raise CypherRejectedError("parameter", "dynamic $ expressions are not allowed")
        if match.group(1) not in allowed:
            raise CypherRejectedError("parameter", f"parameter ${match.group(1)} is not allowed")


def _check_labels(text: str, schema: GraphSchema) -> None:
    known = set(schema.labels) | set(schema.relationships)
    for colon in _COLON_RE.finditer(text):
        first = colon.group(1)
        if first in "!(%" and first:
            raise CypherRejectedError("label", "label expressions with ! ( % are not allowed")
        names = _LABELS_RE.match(text, colon.start(1))
        if names is None:
            continue  # a map value such as {account_id: 'A01'} or a number
        for name in re.findall(_NAME, names.group()):
            if name.lower() not in LITERALS and name not in known:
                raise CypherRejectedError("label", f"label or relationship type {name} is unknown")
    if _IS_RE.search(text):
        raise CypherRejectedError("label", "IS must be followed by NULL or NOT NULL")


def _pairs(text: str, opening: str, closing: str) -> dict[int, int]:
    """Position of each opening bracket -> position of its closing bracket."""
    stack: list[int] = []
    pairs: dict[int, int] = {}
    for i, ch in enumerate(text):
        if ch == opening:
            stack.append(i)
        elif ch == closing and stack:
            pairs[stack.pop()] = i
    return pairs


def _follows_value(text: str, position: int) -> bool:
    """True when the bracket at ``position`` comes right after a value (a name, ``)``, ``]``,
    ``}``) and not after a keyword, an operator or the ``-`` of a relationship pattern."""
    before = text[:position].rstrip()
    if before.endswith((")", "]", "}")):
        return True
    word = _LAST_WORD_RE.search(before)
    return word is not None and word.group(1).lower() not in KEYWORDS


def _calls(text: str) -> list[re.Match[str]]:
    """Every ``name(`` that is not a clause keyword; the name may be dotted."""
    return [m for m in _CALL_RE.finditer(text) if m.group(1).lower() not in KEYWORDS]


def _check_properties(text: str, schema: GraphSchema, calls: list[re.Match[str]]) -> None:
    spans = [m.span(1) for m in calls]  # the dots of apoc.text.join( are not property reads
    for match in _PROPERTY_RE.finditer(text):
        if any(start <= match.start(1) < end for start, end in spans):
            continue
        if match.group(1) not in schema.properties:
            raise CypherRejectedError("property", f"property {match.group(1)} is unknown")
    for match in _MAP_KEY_RE.finditer(text):
        key = match.group(1)
        if key not in schema.properties and key not in DURATION_UNITS:
            raise CypherRejectedError("property", f"map key {key} is not a known property")
    if _ALL_PROPERTIES_RE.search(text):  # n {.*} reads every property, whatever the label
        raise CypherRejectedError("property", "the .* map projection is not allowed")
    for start, end in _pairs(text, "[", "]").items():  # n['text'] reads any property by name
        inside = text[start + 1 : end]
        if _follows_value(text, start) and not (inside.strip() and _INDEX_RE.fullmatch(inside)):
            raise CypherRejectedError("property", "only a number or a range may be used in [ ]")


def _check_functions(schema: GraphSchema, calls: list[re.Match[str]]) -> None:
    allowed = {name.lower() for name in schema.functions}
    for match in calls:
        name = re.sub(r"\s+", "", match.group(1))
        if name.lower() not in allowed:
            raise CypherRejectedError("function", f"function {name} is not allowed")


def _check_paths(text: str, max_path_length: int) -> None:
    for rel in _REL_RE.finditer(text):
        star = _STAR_RE.search(rel.group(1))
        if star is None:
            continue
        low, dots, high = star.groups()
        upper = high if dots else low  # "*3" is exactly 3 hops; "*2.." has no upper bound
        if not upper:
            raise CypherRejectedError("path", "unbounded variable-length pattern")
        if int(upper) > max_path_length:
            raise CypherRejectedError(
                "path", f"variable-length pattern is longer than {max_path_length}"
            )
    quantified = _QUANTIFIED_REL_RE.search(text) is not None
    for start, end in _pairs(text, "(", ")").items():
        before = _LAST_WORD_RE.search(text[:start].rstrip())
        if before is not None and before.group(1).lower() not in KEYWORDS:
            continue  # a function call: count(r) * 2 is arithmetic
        if _ARROW_RE.search(text[start + 1 : end]) and _QUANTIFIER_RE.match(text, end + 1):
            quantified = True  # ((x)-[:T]->(y))+ , ( -[:T]-> ){1,3}
    if quantified:
        raise CypherRejectedError("path", "quantified path patterns are not allowed")


def _force_limit(cypher: str, max_rows: int) -> ValidatedCypher:
    text = cypher.rstrip(" \t\r\n;")
    match = _LIMIT_RE.search(text)
    if match is None:
        return ValidatedCypher(f"{text} LIMIT {max_rows}", max_rows, None)
    original = int(match.group(1))
    if original <= max_rows:
        return ValidatedCypher(text, original, original)
    return ValidatedCypher(text[: match.start(1)] + str(max_rows), max_rows, original)


def validate_cypher(
    cypher: str,
    *,
    max_rows: int,
    max_path_length: int,
    max_query_chars: int,
    allowed_params: Collection[str] = (),
    schema: GraphSchema = GRAPH_SCHEMA,
) -> ValidatedCypher:
    """Return the query to run, or raise `CypherRejectedError` naming the first broken rule."""
    if not cypher.strip(" \t\r\n;"):
        raise CypherRejectedError("empty", "empty query")
    if len(cypher) > max_query_chars:
        raise CypherRejectedError("too_long", f"query is longer than {max_query_chars} characters")
    visible = _strings_blanked(cypher)
    if "`" in visible:
        raise CypherRejectedError("backtick", "backtick identifiers are not allowed")
    if "//" in visible or "/*" in visible:
        raise CypherRejectedError("comment", "comments are not allowed")
    try:
        assert_read_only(cypher, allowed_procedures=())
    except WriteBlockedError as exc:
        raise CypherRejectedError("guard", str(exc)) from exc
    text = blank_literals(cypher)  # no backtick or comment is left, so only strings are blanked
    _check_clauses(text)
    _check_parameters(text, allowed_params)
    _check_labels(text, schema)
    calls = _calls(text)
    _check_properties(text, schema, calls)
    _check_functions(schema, calls)
    _check_paths(text, max_path_length)
    return _force_limit(cypher, max_rows)
