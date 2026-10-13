"""Writes of the API: a human decision on a case, and the audit row of an unmasked PII view."""

from __future__ import annotations

from aml.api.constants import API_VERSION
from aml.api.errors import ApiError
from aml.api.identity import User
from aml.api.reads.cases import translate_case_error
from aml.cases.dispositions import record_disposition
from aml.cases.runner import CaseError
from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database


def record_case_decision(
    db: Database, settings: Settings, user: User, case_id: str, disposition: str, reason: str
) -> int:
    """Store the decision; ``record_disposition`` writes its own audit row, so this does not."""
    try:
        return record_disposition(
            db,
            settings,
            case_id,
            disposition,
            reason=reason,
            actor=user.actor,
            decided_on=settings.data.reference_date,
        )
    except CaseError as exc:
        raise translate_case_error(exc) from exc
    except ValueError as exc:  # the body was validated, so this is a bug, not a bad request
        raise ApiError(422, "invalid_request", str(exc)) from exc


def audit_pii_view(db: Database, user: User, case_id: str, cifs: list[str]) -> None:
    """One ``PII_VIEWED`` row for a response that carried unmasked customer data."""
    audit(
        db,
        module="ui",
        entity_type="case",
        entity_id=case_id,
        decision="PII_VIEWED",
        reason=f"unmasked subject data of case {case_id} shown to {user.actor} (role {user.role})",
        version=API_VERSION,
        actor=user.actor,
        details={"cifs": cifs},
    )
