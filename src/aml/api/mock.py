"""Per-feature sample data: the only module that reads ``fixtures/``.

A feature is mocked when ``ui.mock.<feature>`` is on: the endpoint then returns the fixture and
never calls the real function. With the flag off it returns the real result, or 501 when the real
function does not exist yet - never a number that was not measured.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse

from aml.api import envelope
from aml.api.errors import ApiError
from aml.common.config import Settings

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def features() -> tuple[str, ...]:
    """Names of the features that have a fixture, ascending."""
    return tuple(sorted(p.stem for p in FIXTURE_DIR.glob("*.json")))


def is_mocked(settings: Settings, feature: str) -> bool:
    if feature not in features():
        raise ValueError(f"unknown mock feature {feature!r}")
    return bool(getattr(settings.ui.mock, feature))


def mock_or_live(
    settings: Settings, feature: str, live_fn: Callable[[], Any] | None, **meta: Any
) -> JSONResponse:
    if is_mocked(settings, feature):
        name = f"{feature}.json"
        data = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        return envelope.mock(feature, data, fixture=name, **meta)
    if live_fn is None:
        raise ApiError(
            501,
            "not_implemented",
            f"feature '{feature}' has no live implementation and ui.mock.{feature} is off",
        )
    return envelope.live(feature, live_fn(), **meta)
