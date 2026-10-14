"""The thin adapters between the API and the case summary (7d) and assistant (8c) code.

No SQL and no audit rows here: the called functions write their own. Errors become ``ApiError``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any

from aml.api.errors import ApiError
from aml.api.identity import User
from aml.api.reads.cases import translate_case_error
from aml.assistant.answering import (
    AssistantError,
    AssistantInputError,
    answer_question,
    citation_dict,
)
from aml.assistant.evidence import RetrievalUnavailableError
from aml.assistant.explainer import explain_typology
from aml.assistant.feedback import FeedbackError, record_feedback
from aml.assistant.narrative import draft_narrative
from aml.cases.narrative import NarrativeError, summarize
from aml.cases.runner import CaseError
from aml.cases.view import load_case
from aml.common.config import Settings
from aml.common.db import Database


@contextmanager
def _translated() -> Iterator[None]:
    """Assistant failures as ``ApiError``; an unreachable service passes on to the 503 handler."""
    try:
        yield
    except CaseError as exc:
        raise translate_case_error(exc) from exc
    except AssistantInputError as exc:
        raise ApiError(422, "invalid_request", str(exc)) from exc
    except RetrievalUnavailableError as exc:
        raise ApiError(503, "unavailable", "service unavailable") from exc
    except (AssistantError, NarrativeError) as exc:
        raise ApiError(502, "model_error", str(exc)) from exc


def case_summary(
    db: Database, settings: Settings, case_id: str, language: str | None
) -> dict[str, Any]:
    """The stored (template) summary of a case as plain data; never the LLM generator."""
    try:
        narrative = summarize(db, settings, case_id, generator="template", language=language)
    except CaseError as exc:
        raise translate_case_error(exc) from exc
    except NarrativeError as exc:
        raise ApiError(422, "invalid_request", str(exc)) from exc
    data = asdict(narrative)
    data["citations"] = list(data["citations"])
    return data


def ask(
    db: Database,
    settings: Settings,
    user: User,
    case_id: str,
    question: str,
    language: str,
) -> dict[str, Any]:
    """A cited answer about a case; the case is checked first so an unknown one costs nothing."""
    with _translated():
        load_case(db, case_id, masked=True, scored=False)
        answer = answer_question(
            db, settings, question, case_id=case_id, language=language, actor=user.actor
        )
    return answer.as_dict()


def narrative(
    db: Database, settings: Settings, user: User, case_id: str, language: str
) -> tuple[dict[str, Any], str]:
    """The audited draft narrative of a case and the state of the knowledge layer."""
    with _translated():
        draft = draft_narrative(db, settings, case_id, language=language, actor=user.actor)
    body = asdict(draft.narrative)
    body["citations"] = list(body["citations"])
    data = {"narrative": body, "citations": [citation_dict(c) for c in draft.citations]}
    return data, draft.knowledge


def typologies(db: Database, settings: Settings, case_id: str) -> tuple[dict[str, Any], str]:
    """Why the case matches each typology; read-only, no audit row."""
    with _translated():
        explanation = explain_typology(db, settings, case_id)
    return explanation.as_dict(), explanation.knowledge


def feedback(
    db: Database,
    settings: Settings,
    user: User,
    answer_id: str,
    rating: str,
    comment: str | None,
) -> dict[str, Any]:
    try:
        saved = record_feedback(db, settings, answer_id, rating, comment=comment, actor=user.actor)
    except FeedbackError as exc:
        if str(exc).startswith("unknown answer_id"):
            raise ApiError(404, "not_found", str(exc)) from exc
        raise ApiError(422, "invalid_request", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(422, "invalid_request", str(exc)) from exc
    return {"answer_id": saved.answer_id, "rating": saved.rating, "actor": saved.actor}
