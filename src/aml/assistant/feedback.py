"""Investigator feedback on an assistant answer: a thumbs up/down and an optional comment.

One audit row per rating (append-only; rating again adds a row). It never changes a case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database, split_oracle_script

RATINGS = ("up", "down")
FEEDBACK_VERSION = "feedback/v1"
ANSWER_ID_RE = re.compile(r"^ans-[0-9a-f]{12}$")
COMMENT_MAX = 1000


class FeedbackError(RuntimeError):
    """The feedback cannot be recorded (unknown answer, or no human behind it)."""


@dataclass(frozen=True)
class Feedback:
    answer_id: str
    rating: str
    comment: str | None
    actor: str


def _answer_known(db: Database, answer_id: str) -> bool:
    text = db.sql_file("assistant/answer_known.sql").read_text(encoding="utf-8")
    sql = split_oracle_script(text)[0] if db.backend == "oracle" else text.strip().rstrip(";")
    df = db.query_df(sql, {"answer_id": answer_id})
    return int(df.iloc[0, 0]) > 0


def record_feedback(
    db: Database,
    settings: Settings,
    answer_id: str,
    rating: str,
    *,
    comment: str | None,
    actor: str,
) -> Feedback:
    """Rate an answered (or refused) answer; a failed answer has no id to rate."""
    if not ANSWER_ID_RE.fullmatch(answer_id):
        raise ValueError("answer_id must look like ans-<12 hex digits>")
    if rating not in RATINGS:
        raise ValueError(f"rating must be one of {', '.join(RATINGS)}")
    if comment is not None and len(comment) > COMMENT_MAX:
        raise ValueError(f"comment must be at most {COMMENT_MAX} characters")
    note = comment.strip() if comment is not None else None
    note = note or None
    if actor == settings.audit.system_actor:
        raise FeedbackError("feedback needs a human actor")
    if not _answer_known(db, answer_id):
        raise FeedbackError(f"unknown answer_id {answer_id}")
    audit(
        db,
        module="assistant",
        entity_type="answer",
        entity_id=answer_id,
        decision="ANSWER_RATED",
        reason=f"answer {answer_id} rated {rating} by {actor}",
        version=FEEDBACK_VERSION,
        actor=actor,
        details={"answer_id": answer_id, "rating": rating, "comment": note},
    )
    return Feedback(answer_id, rating, note, actor)
