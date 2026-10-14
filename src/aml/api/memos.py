"""Write of the API: a person's label for a memo key (``relabel_memo`` audits it itself)."""

from __future__ import annotations

from aml.api.errors import ApiError
from aml.api.identity import User
from aml.common.config import Settings
from aml.common.db import Database
from aml.memo.classify import MemoError
from aml.memo.relabel import Relabel, relabel_memo


def _translate(exc: Exception) -> ApiError:
    text = str(exc)
    if text.startswith("unknown memo key"):
        return ApiError(404, "not_found", text)
    if text.startswith("a relabel needs a human actor"):
        return ApiError(403, "forbidden", text)
    return ApiError(422, "invalid_request", text)  # short or ambiguous prefix, or any other


def record_memo_relabel(
    db: Database, settings: Settings, user: User, key: str, category: str, reason: str
) -> Relabel:
    """Store the relabel as ``user``; the actor is never taken from the request body."""
    try:
        return relabel_memo(db, settings, key, category, reason=reason, actor=user.actor)
    except (MemoError, ValueError) as exc:
        raise _translate(exc) from exc
