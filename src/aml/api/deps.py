"""FastAPI dependencies: the settings, the calling user, and one database per request."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request

from aml.api.identity import USER_HEADER, User, resolve_user
from aml.common.config import Settings
from aml.common.db import Database, get_db

# A page loads several panels at once. DuckDB releases its file when the last connection of the
# process closes, and a connect that overlaps that close fails with "file is being used by
# another process": opening and closing therefore never run at the same time.
_OPEN_CLOSE = threading.Lock()


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def current_user(
    settings: Annotated[Settings, Depends(get_app_settings)],
    x_aml_user: Annotated[str | None, Header(alias=USER_HEADER)] = None,
) -> User:
    return resolve_user(settings, x_aml_user)


def get_database(
    request: Request, _user: Annotated[User, Depends(current_user)]
) -> Iterator[Database]:
    """A given ``db`` (tests) is shared and left open; else open one per request and close it.

    Depends on ``current_user`` so an unidentified request gets its 401 before any connection.
    """
    shared: Database | None = request.app.state.db
    if shared is not None:
        yield shared
        return
    with _OPEN_CLOSE:
        db = get_db(request.app.state.settings)
    try:
        yield db
    finally:
        with _OPEN_CLOSE:
            db.close()
