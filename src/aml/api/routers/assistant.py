"""The assistant endpoints (Phase 9c): question, draft narrative, typology explainer, feedback."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from aml.api import assistant, envelope
from aml.api.constants import API_PREFIX
from aml.api.deps import current_user, get_app_settings, get_database
from aml.api.identity import User
from aml.assistant.feedback import ANSWER_ID_RE, COMMENT_MAX
from aml.common.config import Settings
from aml.common.db import Database

FEATURE = "assistant"
router = APIRouter(prefix=API_PREFIX)

Language = Literal["vi", "en"]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    question: Question
    language: Language = "vi"


class NarrativeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language = "vi"


class FeedbackBody(BaseModel):
    """No ``actor`` field: the actor is always the user of the request."""

    model_config = ConfigDict(extra="forbid")

    answer_id: Annotated[str, Field(pattern=ANSWER_ID_RE.pattern)]
    rating: Literal["up", "down"]
    comment: Annotated[str, Field(max_length=COMMENT_MAX)] | None = None


@router.post("/assistant/chat")
def post_chat(
    body: ChatBody,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    data = assistant.ask(db, settings, user, body.case_id, body.question, body.language)
    return envelope.live(FEATURE, data, pii="masked")


@router.post("/cases/{case_id}/narrative")
def post_narrative(
    case_id: str,
    body: NarrativeBody,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    data, knowledge = assistant.narrative(db, settings, user, case_id, body.language)
    return envelope.live(FEATURE, data, pii="masked", knowledge=knowledge)


@router.get("/cases/{case_id}/typologies")
def get_typologies(
    case_id: str,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    _user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    data, knowledge = assistant.typologies(db, settings, case_id)
    return envelope.live(FEATURE, data, pii="masked", knowledge=knowledge)


@router.post("/assistant/feedback")
def post_feedback(
    body: FeedbackBody,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    data = assistant.feedback(db, settings, user, body.answer_id, body.rating, body.comment)
    return envelope.live(FEATURE, data, status=201)
