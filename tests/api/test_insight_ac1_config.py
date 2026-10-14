"""AC1 of specs/ui-mock-pages.md: config, the ten new routes, live source and auth."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from aml.common.config import MockConfig, load_settings

from .helpers import mod
from .insight_helpers import C1, V1, fakes, rows_of
from .live_helpers import audit_total

NEW_ROUTES = {
    ("GET", f"{V1}/cases/scores"),
    ("GET", f"{V1}/cases/{{case_id}}/summary"),
    ("POST", f"{V1}/cases/{{case_id}}/narrative"),
    ("GET", f"{V1}/cases/{{case_id}}/typologies"),
    ("POST", f"{V1}/assistant/chat"),
    ("POST", f"{V1}/assistant/feedback"),
    ("GET", f"{V1}/metrics/funnel"),
    ("GET", f"{V1}/metrics/detections"),
    ("GET", f"{V1}/metrics/below-the-line/auto-cleared"),
    ("GET", f"{V1}/metrics/suppression"),
}
FIVE_GET = [
    f"{V1}/cases/scores",
    f"{V1}/metrics/funnel",
    f"{V1}/metrics/detections",
    f"{V1}/metrics/below-the-line/auto-cleared",
    f"{V1}/metrics/suppression",
]


def _calls(c: Any) -> list[Any]:
    """All ten new routes, with valid bodies for the POSTs."""
    return [
        c.get(f"{V1}/cases/scores"),
        c.get(f"{V1}/cases/{C1}/summary"),
        c.post(f"{V1}/cases/{C1}/narrative", json={}),
        c.get(f"{V1}/cases/{C1}/typologies"),
        c.post(f"{V1}/assistant/chat", json={"case_id": C1, "question": "Tài khoản A01?"}),
        c.post(
            f"{V1}/assistant/feedback",
            json={"answer_id": "ans-9504e4efe5dd", "rating": "up", "comment": None},
        ),
        c.get(f"{V1}/metrics/funnel"),
        c.get(f"{V1}/metrics/detections"),
        c.get(f"{V1}/metrics/below-the-line/auto-cleared"),
        c.get(f"{V1}/metrics/suppression"),
    ]


def _route_set(c: Any, prefix: str = "") -> set[tuple[str, str]]:
    out = set()
    for r in c.app.routes:
        path = getattr(r, "path", "")
        for method in getattr(r, "methods", None) or ():
            if method not in ("HEAD", "OPTIONS") and path.startswith(prefix):
                out.add((method, path))
    return out


def test_ac1_metrics_defaults() -> None:
    m = load_settings(environ={}).metrics
    assert m.minutes_per_alert == 15
    assert m.sample_size == 20
    assert m.max_sample_size == 200


def test_ac1_minutes_per_alert_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="metrics minutes_per_alert must be >= 1"):
        load_settings(environ={"AML__METRICS__MINUTES_PER_ALERT": "0"})


def test_ac1_sample_size_must_not_exceed_max() -> None:
    with pytest.raises(
        ValidationError, match="metrics sample_size must be between 1 and max_sample_size"
    ):
        load_settings(environ={"AML__METRICS__SAMPLE_SIZE": "201"})


def test_ac1_mock_config_keeps_only_sample() -> None:
    assert set(MockConfig.model_fields) == {"sample"}


def test_ac1_exactly_ten_new_routes(schema: Any, client: Any) -> None:
    routes = _route_set(client())
    assert routes >= NEW_ROUTES
    mine = _route_set(client(), f"{V1}/assistant") | _route_set(client(), f"{V1}/metrics")
    assert mine == {r for r in NEW_ROUTES if "/assistant" in r[1] or "/metrics" in r[1]}


@pytest.mark.parametrize("path", FIVE_GET)
def test_ac1_five_get_routes_are_live_on_schema(schema: Any, client: Any, path: str) -> None:
    r = client(user="analyst01").get(path)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "live"
    assert r.headers["X-AML-Source"] == "live"


def test_ac1_cases_scores_is_not_caught_by_case_id_route(schema: Any, client: Any) -> None:
    r = client(user="analyst01").get(f"{V1}/cases/scores")
    assert r.status_code == 200, r.text
    assert r.json()["feature"] == "case_scores"


def test_ac1_unknown_user_is_401_on_all_ten(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch)
    before = audit_total(api_mini)
    responses = _calls(client(user="nobody"))
    assert len(responses) == 10
    for r in responses:
        assert r.status_code == 401, r.text
        assert r.json()["error"]["code"] == "unknown_user"
    assert audit_total(api_mini) == before


def test_ac1_missing_user_is_401_on_all_ten(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch)
    before = audit_total(api_mini)
    responses = _calls(client(AML__UI__DEFAULT_USER=""))
    assert len(responses) == 10
    for r in responses:
        assert r.status_code == 401, r.text
        assert r.json()["error"]["code"] == "missing_user"
    assert audit_total(api_mini) == before
    assert rows_of(api_mini)["audit_log"] == before


def test_ac1_metrics_package_exists() -> None:
    assert mod("aml.metrics") is not None
