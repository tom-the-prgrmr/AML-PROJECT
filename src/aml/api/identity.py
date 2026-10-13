"""Who is calling: the actor comes from a header, the role from ``ui.users``, never the client."""

from __future__ import annotations

from dataclasses import dataclass

from aml.api.errors import ApiError
from aml.common.config import Settings

USER_HEADER = "X-AML-User"
ROLE_PII = {"analyst": "masked", "supervisor": "full"}  # role -> PII level of the responses


@dataclass(frozen=True)
class User:
    actor: str
    role: str
    pii: str  # "masked" | "full"


def resolve_user(settings: Settings, header_value: str | None) -> User:
    """The user behind a request; no header means ``ui.default_user`` (401 when there is none)."""
    actor = header_value or settings.ui.default_user
    if not actor:
        raise ApiError(401, "missing_user", f"the {USER_HEADER} header is required")
    role = settings.ui.users.get(actor)
    if role is None:
        raise ApiError(401, "unknown_user", f"unknown user '{actor}'")
    return User(actor=actor, role=role, pii=ROLE_PII[role])
