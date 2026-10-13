"""Neo4j access for the projection: driver, `.cypher` files, guarded reads and file-based writes.

Reads go through the guard and a READ session. Writes only run files whose name starts with one of
``WRITE_PREFIXES``; there is no function that writes an arbitrary Cypher string.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import neo4j
import pandas as pd

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database, ServiceUnavailableError
from aml.graph.neo4j.guard import (
    GUARD_VERSION,
    GraphError,
    WriteBlockedError,
    assert_read_only,
)

CYPHER_ROOT = Path(__file__).resolve().parent / "cypher"
WRITE_PREFIXES: tuple[str, ...] = ("schema.cypher", "sync/")
COUNTERS = (
    "nodes_created", "nodes_deleted", "relationships_created", "relationships_deleted",
    "properties_set",
)  # fmt: skip
QUERY_AUDIT_LIMIT = 2000


class QueryTimeoutError(GraphError):
    """A read query ran past ``neo4j.read_timeout_seconds`` and the server stopped it."""


# ---------------------------------------------------------------- .cypher files
def cypher_file(name: str) -> Path:
    path = (CYPHER_ROOT / name).resolve()
    if not path.is_relative_to(CYPHER_ROOT) or not path.is_file():
        raise FileNotFoundError(f"no Cypher file {name!r} under {CYPHER_ROOT}")
    return path


def split_statements(text: str) -> list[str]:
    """Split a file into statements, each ending with ';' at a line end (// lines dropped)."""
    statements: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("//"):
            continue
        current.append(line)
        if line.rstrip().endswith(";"):
            statements.append("\n".join(current).rstrip().removesuffix(";").strip())
            current = []
    if "".join(current).strip():
        raise ValueError("Cypher statement without a terminating ';' at the end of a line")
    return statements


def load_statements(name: str) -> list[str]:
    return split_statements(cypher_file(name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- driver
def open_driver(settings: Settings) -> neo4j.Driver:
    cfg = settings.neo4j
    driver = None
    try:
        driver = neo4j.GraphDatabase.driver(
            cfg.uri,
            auth=(cfg.user, cfg.password),
            connection_timeout=5,
            # "constraint already exists" notes from the idempotent schema are not worth a log line
            notifications_min_severity="WARNING",
        )
        driver.verify_connectivity()
    except Exception as exc:  # the driver raises several unrelated exception types
        if driver is not None:
            driver.close()
        raise ServiceUnavailableError(f"cannot connect to Neo4j at {cfg.uri}: {exc}") from exc
    return driver


# ---------------------------------------------------------------- reads
def _native(value: Any) -> Any:
    """neo4j.time values become datetime / date; lists are converted element-wise."""
    if isinstance(value, list):
        return [_native(v) for v in value]
    to_native = getattr(value, "to_native", None)
    return to_native() if callable(to_native) else value


def _fetch(tx: neo4j.ManagedTransaction, cypher: str, params: Mapping[str, Any]) -> pd.DataFrame:
    result = tx.run(cypher, dict(params))
    columns = list(result.keys())
    data = [[_native(v) for v in record.values()] for record in result]
    frame = pd.DataFrame(data, columns=columns)
    for i, column in enumerate(columns):  # keep datetime as Python objects, not pandas Timestamp
        if any(isinstance(row[i], datetime) for row in data):
            frame[column] = pd.Series([row[i] for row in data], dtype=object, index=frame.index)
    return frame


def _audit_blocked(db: Database, cypher: str, exc: WriteBlockedError, actor: str | None) -> None:
    extra: dict[str, Any] = {"actor": actor} if actor else {}
    audit(
        db,
        module="graph",
        entity_type="cypher",
        entity_id=hashlib.sha256(cypher.encode("utf-8")).hexdigest()[:16],
        decision="QUERY_BLOCKED",
        reason=str(exc),
        version=GUARD_VERSION,
        details={"query": cypher[:QUERY_AUDIT_LIMIT]},
        **extra,
    )


def run_read(
    driver: neo4j.Driver,
    settings: Settings,
    cypher: str,
    params: Mapping[str, Any] | None = None,
    *,
    audit_db: Database | None = None,
    actor: str | None = None,
    timeout: float | None = None,
    procedures: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Guard the query, run it in a READ session; columns are the RETURN keys (even with 0 rows).

    ``procedures`` (None = ``neo4j.read_procedures``) is the allow-list the guard applies; the GDS
    runner passes ``gds.procedures`` for its own ``.cypher`` files only.

    ``timeout`` (seconds; None = ``neo4j.read_timeout_seconds``) is enforced by the server, which
    rolls the transaction back; it surfaces as `QueryTimeoutError` and is not retried.
    """
    try:
        allowed = settings.neo4j.read_procedures if procedures is None else procedures
        assert_read_only(cypher, allowed_procedures=allowed)
    except WriteBlockedError as exc:
        if audit_db is not None:
            _audit_blocked(audit_db, cypher, exc, actor)
        raise
    seconds = settings.neo4j.read_timeout_seconds if timeout is None else timeout
    work = neo4j.unit_of_work(timeout=seconds)(_fetch)
    try:
        with driver.session(
            database=settings.neo4j.database, default_access_mode=neo4j.READ_ACCESS
        ) as session:
            return session.execute_read(work, cypher, params or {})
    except neo4j.exceptions.Neo4jError as exc:
        if "TransactionTimedOut" in (exc.code or ""):
            raise QueryTimeoutError(f"query exceeded {seconds:g} s") from exc
        raise
    except (neo4j.exceptions.ServiceUnavailable, neo4j.exceptions.SessionExpired) as exc:
        # the cached driver outlived the server: report it like a failed connect
        raise ServiceUnavailableError(f"lost the connection to Neo4j: {exc}") from exc


def run_read_file(
    driver: neo4j.Driver,
    settings: Settings,
    name: str,
    params: Mapping[str, Any] | None = None,
    *,
    timeout: float | None = None,
    procedures: Sequence[str] | None = None,
) -> pd.DataFrame:
    statements = load_statements(name)
    if len(statements) != 1:
        raise GraphError(f"{name} must hold exactly one statement, found {len(statements)}")
    return run_read(driver, settings, statements[0], params, timeout=timeout, procedures=procedures)


# ---------------------------------------------------------------- writes
def run_write_file(
    driver: neo4j.Driver,
    settings: Settings,
    name: str,
    params: Mapping[str, Any] | None = None,
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, int]:
    """Run every statement of a write file; with ``rows``, once per batch as ``$rows``.

    Each run is an auto-commit transaction (``session.run``): `CALL (x) { } IN TRANSACTIONS`
    does not work inside ``execute_write``. Returns the summed counters.
    """
    if not name.startswith(WRITE_PREFIXES):
        raise GraphError(f"{name} is not a write file (allowed: {', '.join(WRITE_PREFIXES)})")
    statements = load_statements(name)
    size = settings.graph_sync.batch_size
    totals = dict.fromkeys(COUNTERS, 0)
    with driver.session(database=settings.neo4j.database) as session:
        for statement in statements:
            if rows is None:
                runs: list[dict[str, Any]] = [dict(params or {})]
            else:
                runs = [
                    {**(params or {}), "rows": list(rows[i : i + size])}
                    for i in range(0, len(rows), size)
                ]
            for run_params in runs:
                counters = session.run(statement, run_params).consume().counters
                for key in COUNTERS:
                    totals[key] += int(getattr(counters, key))
    return totals
