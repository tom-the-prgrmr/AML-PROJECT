"""Text2Cypher: the local model writes one read query, the guard decides whether it runs.

The model is small and follows injected instructions, so nothing here relies on the prompt being
obeyed. Every generated query is validated by `validate_cypher` (allow-listed labels, properties
and functions, forced LIMIT), runs in a READ session with a server-side timeout and no procedure
at all, and is written to ``audit_log`` whether it ran, was rejected or failed. The prompt holds
the schema and fixed examples only: no row of the database.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import neo4j
import pandas as pd

from aml.assistant.cypher_guard import (
    T2C_GUARD_VERSION,
    CypherRejectedError,
    ValidatedCypher,
    validate_cypher,
)
from aml.assistant.evidence import (
    PLACEHOLDER,
    Evidence,
    RetrievalError,
    RetrievalUnavailableError,
    UntrustedField,
    cite,
    fmt_ts,
    is_safe_token,
    untrusted_field,
)
from aml.assistant.knowledge.model import ID_PATTERNS as KNOWLEDGE_ID_PATTERNS
from aml.assistant.llm import LLMClient
from aml.assistant.schema import GRAPH_SCHEMA, schema_text
from aml.cases.values import plain
from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database, ServiceUnavailableError
from aml.graph.neo4j.client import run_read
from aml.graph.neo4j.guard import GraphError
from aml.graph.neo4j.session import shared_driver

PROMPT_VERSION = "t2c-prompt/v1"
TEXT_LIMIT = 2000  # characters of the question / generated text kept in results and audit
MESSAGE_LIMIT = 300
OMITTED = "[omitted]"
JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"cypher": {"type": "string"}},
    "required": ["cypher"],
}
ID_COLUMNS = {
    "txn_id": "txn",
    "account_id": "account",
    "golden_customer_id": "customer",
    "case_id": "case",
    "typology_id": "typology",
    "red_flag_id": "red_flag",
    "procedure_id": "procedure",
    "regulation_id": "regulation",
}
RULES_TEXT = """You translate a question about a bank's transaction graph into ONE Cypher query.
Reply with JSON only: {"cypher": "<query>"}.

Rules:
- One read query that starts with MATCH and ends with LIMIT. Never write, never CALL anything.
- Use only the labels, relationship types and properties of the schema below.
- Return properties (for example a.account_id), never a whole node or relationship.
- Keep id columns under their own name: txn_id, account_id, golden_customer_id, case_id.
- ts is a LOCAL DATETIME: compare it with localdatetime('YYYY-MM-DDTHH:MM:SS'), never datetime().
- Amounts are whole numbers of VND. Ids are strings: A... is an account, T... a transaction.
- No comments, no backticks, no UNION, no UNWIND, no subqueries; a variable-length pattern needs
  an upper bound of at most 3, for example [:TRANSFERRED_TO*1..3]."""
EXAMPLES = """Examples:
Q: Which accounts received money from account A0000000001?
{"cypher": "MATCH (a:Account {account_id: 'A0000000001'})-[r:TRANSFERRED_TO]->(b:Account) \
RETURN r.txn_id, b.account_id, r.amount ORDER BY r.amount DESC LIMIT 10"}
Q: How many transfers of at least 100 million VND happened since April 2026?
{"cypher": "MATCH (:Account)-[r:TRANSFERRED_TO]->(:Account) \
WHERE r.ts >= localdatetime('2026-04-01T00:00:00') AND r.amount >= 100000000 \
RETURN count(r) AS transfers LIMIT 1"}
Q: Which customers share a device with customer G-CIF00000001?
{"cypher": "MATCH (c:Customer {golden_customer_id: 'G-CIF00000001'})-[:USES_DEVICE]->(:Device)\
<-[:USES_DEVICE]-(o:Customer) RETURN DISTINCT o.golden_customer_id LIMIT 10"}"""

# a citation is made only when the cell has the shape of an id of that kind, so that
# `RETURN a.currency AS txn_id` cannot produce "txn:VND"
ID_VALUE_PATTERNS = {
    "txn": re.compile(r"T[A-Z0-9]{1,15}"),
    "account": re.compile(r"A[A-Z0-9]{1,15}|EXT-\d{1,15}"),
    "customer": re.compile(r"G-[A-Za-z0-9-]{1,40}"),
    "case": re.compile(r"C-[A-Za-z0-9]+-\d{8}"),
    **{
        kind: re.compile(KNOWLEDGE_ID_PATTERNS[label])
        for kind, label in (
            ("typology", "Typology"),
            ("red_flag", "RedFlag"),
            ("procedure", "Procedure"),
            ("regulation", "Regulation"),
        )
    },
}
AGGREGATES = ("count", "sum", "avg", "min", "max", "collect", "size")

Runner = Callable[[str, Mapping[str, Any]], pd.DataFrame]
_PROPERTY_COLUMN_RE = re.compile(r"[A-Za-z_]\w{0,15}\.([A-Za-z_]\w*)")
_AGGREGATE_COLUMN_RE = re.compile(
    rf"(?:{'|'.join(AGGREGATES)})\((?:DISTINCT )?(\*|[A-Za-z_]\w{{0,15}}(?:\.([A-Za-z_]\w*))?)\)",
    re.IGNORECASE,
)
_ALIAS_RE = re.compile(r"[a-z_]{1,24}")


class Text2CypherError(RetrievalError):
    """Text2Cypher cannot be used at all (it is switched off)."""


@dataclass(frozen=True)
class GeneratedQuery:
    attempt: int
    generated: str  # what the model returned (cut to 2000 characters)
    executed: str | None  # the query that ran; None when it was rejected
    status: str  # "EXECUTED" | "REJECTED" | "FAILED"
    rule: str | None  # a guard rule or "no_query"; None when EXECUTED
    message: str
    rows: int
    seconds: float


@dataclass(frozen=True)
class Text2CypherResult:
    evidence: tuple[Evidence, ...]
    queries: tuple[GeneratedQuery, ...]


# ---------------------------------------------------------------- prompt
def build_messages(question: str, *, allowed_params: Collection[str] = ()) -> list[dict[str, str]]:
    """System = rules + schema + fixed examples; the question is only in the user message."""
    system = [RULES_TEXT]
    if allowed_params:
        names = ", ".join(f"${name}" for name in allowed_params)
        system.append(
            f"The question is about one case. You may use these parameters, and no other: {names}."
        )
    system += [schema_text(), EXAMPLES]
    return [
        {"role": "system", "content": "\n\n".join(system)},
        {"role": "user", "content": question},
    ]


def _extract(reply: str) -> str | None:
    """The ``cypher`` string of the model's JSON reply, or None when there is no usable one."""
    try:
        parsed = json.loads(reply)
    except ValueError:
        return None
    cypher = parsed.get("cypher") if isinstance(parsed, dict) else None
    return cypher if isinstance(cypher, str) and cypher.strip() else None


# ---------------------------------------------------------------- rows -> Evidence
def _scalar(value: Any) -> str | None:
    """How a number, bool or date is printed; None when ``value`` is none of them."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, datetime):
        return fmt_ts(value)
    if isinstance(value, date):
        return value.isoformat()
    return None


def _cell(name: str, value: Any, max_chars: int, unsafe: list[UntrustedField]) -> str:
    """One printed cell. Free text goes to ``unsafe``; nodes, relationships, maps are left out."""
    if value is None:
        return "null"
    printed = _scalar(value)
    if printed is not None:
        return printed
    if isinstance(value, list | tuple):
        parts = [p if (p := _scalar(v)) is not None else v for v in value]
        if all(isinstance(p, str) and is_safe_token(p) for p in parts):
            return ",".join(parts)
        if all(isinstance(p, str) for p in parts):
            value = ", ".join(parts)
        else:
            return OMITTED
    if isinstance(value, str):
        if is_safe_token(value):
            return value
        unsafe.extend(untrusted_field(name, value, max_chars))
        return PLACEHOLDER
    return OMITTED


def _native(value: Any) -> Any:
    """A DataFrame cell as a plain Python value (lists and driver objects pass through)."""
    return value if isinstance(value, list | tuple | dict) else plain(value)


def printable_column(column: str) -> bool:
    """True when a column name may be printed in trusted text.

    The model chooses column names (``RETURN ... AS <alias>``), so only names built from schema
    properties (``a.account_id``), a short aggregate of them (``sum(r.amount)``, ``count(*)``) or
    a short lower-case alias are printed; any other column is shown as ``col<j>``.
    """
    known = GRAPH_SCHEMA.properties
    prop = _PROPERTY_COLUMN_RE.fullmatch(column)
    if prop is not None:
        return prop.group(1) in known
    aggregate = _AGGREGATE_COLUMN_RE.fullmatch(column)
    if aggregate is not None:
        return aggregate.group(2) is None or aggregate.group(2) in known
    return column in known or _ALIAS_RE.fullmatch(column) is not None


def _citation(column: str, value: Any) -> str | None:
    kind = ID_COLUMNS.get(column.rsplit(".", 1)[-1])
    if kind is None or not is_safe_token(value) or not ID_VALUE_PATTERNS[kind].fullmatch(value):
        return None
    return cite(kind, value)


def rows_to_evidence(frame: pd.DataFrame, settings: Settings) -> list[Evidence]:
    """One fact per row: ``Query row i: column=value, ...``; id columns become citations."""
    max_chars = settings.assistant.retrieval.max_untrusted_chars
    out = []
    for i, record in enumerate(frame.to_dict("records"), start=1):
        unsafe: list[UntrustedField] = []
        parts, citations, data = [], [], {}
        for j, (column, raw) in enumerate(record.items(), start=1):
            value = _native(raw)
            name = str(column) if printable_column(str(column)) else f"col{j}"
            field = name if is_safe_token(name) else f"col{j}"
            parts.append(f"{name}={_cell(field, value, max_chars, unsafe)}")
            data[str(column)] = value
            citation = _citation(str(column), value)
            if citation is not None:
                citations.append(citation)
        out.append(
            Evidence(
                f"E{i}",
                "fact",
                "text2cypher",
                "neo4j",
                f"Query row {i}: {', '.join(parts)}",
                tuple(dict.fromkeys(citations)),
                data,
                tuple(unsafe),
            )
        )
    return out


# ---------------------------------------------------------------- the loop
def _default_runner(settings: Settings) -> Runner:
    def run(cypher: str, params: Mapping[str, Any]) -> pd.DataFrame:
        return run_read(
            shared_driver(settings),
            settings,
            cypher,
            params,
            procedures=(),
            timeout=settings.assistant.text2cypher.timeout_seconds,
        )

    return run


def _short(exc: BaseException) -> str:
    text = str(getattr(exc, "message", None) or exc)
    return " ".join(text.split())[:MESSAGE_LIMIT]


def text2cypher(
    db: Database,
    settings: Settings,
    question: str,
    *,
    llm: LLMClient,
    case_id: str | None = None,
    golden_customer_id: str | None = None,
    actor: str | None = None,
    runner: Runner | None = None,
) -> Text2CypherResult:
    """Generate, validate and run one query for ``question``; every attempt is audited.

    A rejected query is regenerated until ``max_attempts`` is used up; a query that fails on the
    server is not. Running out of attempts returns a result without evidence (it does not raise).
    """
    cfg = settings.assistant.text2cypher
    if not cfg.enabled:
        raise Text2CypherError("text2cypher is disabled")
    given = {"case_id": case_id, "golden_customer_id": golden_customer_id}
    params = {k: v for k, v in given.items() if v is not None}
    run = runner or _default_runner(settings)
    messages = build_messages(question, allowed_params=tuple(params))
    queries: list[GeneratedQuery] = []
    evidence: list[Evidence] = []

    def record(
        attempt: int, generated: str, started: float, status: str, rule: str | None,
        message: str, valid: ValidatedCypher | None = None, rows: int = 0,
    ) -> None:  # fmt: skip
        seconds = round(time.perf_counter() - started, 3)
        executed = valid.text if valid is not None else None
        queries.append(
            GeneratedQuery(
                attempt, generated[:TEXT_LIMIT], executed, status, rule, message, rows, seconds
            )
        )
        reasons = {
            "EXECUTED": f"generated query passed the guard and returned {rows} row(s)",
            "REJECTED": f"generated query rejected by rule {rule}: {message}",
            "FAILED": f"generated query failed: {message}",
        }
        audit(
            db,
            module="assistant",
            entity_type="text2cypher",
            entity_id=hashlib.sha256(generated.encode("utf-8")).hexdigest()[:16],
            decision=f"CYPHER_{status}",
            reason=reasons[status],
            version=T2C_GUARD_VERSION,
            actor=actor or settings.audit.system_actor,
            details={
                "question": question[:TEXT_LIMIT],
                "generated": generated[:TEXT_LIMIT],
                "executed": executed,
                "rule": rule,
                "rows": rows,
                "attempt": attempt,
                "limit": valid.limit if valid is not None else None,
                "seconds": seconds,
                "case_id": case_id,
                "prompt_version": PROMPT_VERSION,
                "guard_version": T2C_GUARD_VERSION,
            },
        )

    for attempt in range(1, cfg.max_attempts + 1):
        started = time.perf_counter()
        reply = llm.chat(messages, json_schema=JSON_SCHEMA)  # type: ignore[arg-type]
        cypher = _extract(reply)
        try:
            if cypher is None:
                raise CypherRejectedError("no_query", "the model returned no query")
            valid = validate_cypher(
                cypher,
                max_rows=cfg.max_rows,
                max_path_length=cfg.max_path_length,
                max_query_chars=cfg.max_query_chars,
                allowed_params=tuple(params),
            )
        except CypherRejectedError as exc:
            record(attempt, cypher or reply, started, "REJECTED", exc.rule, str(exc))
            messages = [
                *messages,
                {"role": "assistant", "content": reply},
                {"role": "user", "content": f"Rejected: {exc}. Return a corrected query."},
            ]
            continue
        try:
            frame = run(valid.text, params).head(cfg.max_rows)
        except ServiceUnavailableError as exc:
            raise RetrievalUnavailableError(f"neo4j not available: {exc}") from exc
        except (GraphError, neo4j.exceptions.Neo4jError) as exc:
            record(attempt, cypher, started, "FAILED", None, _short(exc), valid)
            break
        evidence = rows_to_evidence(frame, settings)
        record(attempt, cypher, started, "EXECUTED", None, "", valid, rows=len(evidence))
        break
    return Text2CypherResult(tuple(evidence), tuple(queries))
