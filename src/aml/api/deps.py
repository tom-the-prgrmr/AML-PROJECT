"""FastAPI dependencies: the settings, the calling user, and one database per request."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request

from aml.api.identity import USER_HEADER, User, resolve_user
from aml.common.config import Settings
from aml.common.db import Database, get_db


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
    db = get_db(request.app.state.settings)
    try:
        yield db
    finally:
        db.close()
