"""Adapters that put the ``neo4j_graphrag`` package behind this project's read-only rules.

The package does not go through ``run_read``: it calls ``driver.execute_query`` with query text it
assembles itself (a ``retrieval_query`` tail is appended unchecked), without a timeout and without
the guard. `GuardedDriver` is the driver handed to the package instead of the real one, and it
keeps every guarantee of ``run_read``: READ routing only, ``assert_read_only`` on the final text,
a server-side timeout, and no way to open a session. `LLMEmbedder` makes the package embed through
the project's own `LLMClient` (cache, fake client), so none of its model classes is used.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import neo4j
from neo4j_graphrag.embeddings.base import Embedder

from aml.assistant.llm import LLMClient
from aml.common.config import Settings
from aml.common.db import ServiceUnavailableError
from aml.graph.neo4j.client import QueryTimeoutError
from aml.graph.neo4j.guard import WriteBlockedError, assert_read_only

READ = neo4j.RoutingControl.READ


class GuardedDriver(neo4j.Driver):
    """A read-only face of a real driver (a subclass because the package checks ``isinstance``).

    It opens no connection of its own, so ``neo4j.Driver.__init__`` is deliberately not called.
    """

    def __init__(
        self, inner: neo4j.Driver, settings: Settings, *, timeout: float | None = None
    ) -> None:
        self._inner = inner
        self._settings = settings
        self._timeout = settings.neo4j.read_timeout_seconds if timeout is None else timeout
        self._allowed = [*settings.neo4j.read_procedures, *settings.assistant.vector_procedures]
        # the package overwrites driver._pool.pool_config.user_agent: give it a stand-in to write
        # on, so the shared driver keeps its own user agent
        self._pool = SimpleNamespace(pool_config=SimpleNamespace(user_agent=None))

    def execute_query(  # type: ignore[override]
        self,
        query_: Any,
        parameters_: dict[str, Any] | None = None,
        routing_: Any = neo4j.RoutingControl.WRITE,
        database_: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Guard the statement, then forward it as a READ query with a server-side timeout."""
        if routing_ != READ:
            raise WriteBlockedError("only READ routing is allowed on the guarded driver")
        if kwargs:
            raise WriteBlockedError(
                f"unsupported execute_query option(s) on the guarded driver: {sorted(kwargs)}"
            )
        text = str(getattr(query_, "text", query_))
        assert_read_only(text, allowed_procedures=self._allowed)
        try:
            return self._inner.execute_query(
                neo4j.Query(text, timeout=self._timeout),  # type: ignore[arg-type]
                parameters_,
                routing_=READ,
                database_=self._settings.neo4j.database,
            )
        except neo4j.exceptions.Neo4jError as exc:
            if "TransactionTimedOut" in (exc.code or ""):
                raise QueryTimeoutError(f"query exceeded {self._timeout:g} s") from exc
            raise
        except (neo4j.exceptions.ServiceUnavailable, neo4j.exceptions.SessionExpired) as exc:
            raise ServiceUnavailableError(f"lost the connection to Neo4j: {exc}") from exc

    def session(self, **config: Any) -> Any:
        raise WriteBlockedError("sessions are not available on the guarded driver")

    def close(self) -> None:
        """Nothing to close: the wrapped driver belongs to its owner."""

    def __del__(self) -> None:  # the base class warns about an unclosed driver
        pass


class LLMEmbedder(Embedder):
    """The package's embedder interface on top of `LLMClient.embed`."""

    def __init__(self, llm: LLMClient) -> None:
        super().__init__()
        self._llm = llm

    def embed_query(self, text: str) -> list[float]:
        return self._llm.embed([text])[0]
