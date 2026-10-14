"""Page size and offset checks shared by the list endpoints."""

from __future__ import annotations

from aml.api.errors import ApiError
from aml.common.config import Settings


def resolve_limit(settings: Settings, limit: int | None) -> int:
    """``None`` -> the default page size; outside 1..max_page_size -> 422."""
    if limit is None:
        return settings.ui.page_size
    if not 1 <= limit <= settings.ui.max_page_size:
        raise ApiError(
            422, "invalid_request", f"limit must be between 1 and {settings.ui.max_page_size}"
        )
    return limit


def check_offset(offset: int) -> int:
    if offset < 0:
        raise ApiError(422, "invalid_request", "offset must be 0 or more")
    return offset
