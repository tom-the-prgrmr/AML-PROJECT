"""API side of a screening review: the actor is the user of the request, errors become 404."""

from __future__ import annotations

from aml.api.errors import ApiError
from aml.api.identity import User
from aml.common.config import Settings
from aml.common.db import Database
from aml.screening.review import ScreeningReview, ScreeningReviewError, record_review


def record_hit_review(
    db: Database,
    settings: Settings,
    user: User,
    cif: str,
    entry_id: str,
    decision: str,
    reason: str,
) -> ScreeningReview:
    """Store the review (``record_review`` writes its own audit row, so this does not)."""
    try:
        return record_review(db, settings, cif, entry_id, decision, reason=reason, actor=user.actor)
    except ScreeningReviewError as exc:
        if str(exc).startswith("unknown screening hit"):
            raise ApiError(404, "not_found", str(exc)) from exc
        raise
    except ValueError as exc:  # the body was validated, so this is a bug, not a bad request
        raise ApiError(422, "invalid_request", str(exc)) from exc
