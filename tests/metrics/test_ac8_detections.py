"""AC8 of specs/ui-mock-pages.md: GET /api/v1/metrics/detections and ``aml.metrics.detections``."""

from __future__ import annotations

import math
from typing import Any

import pytest

from tests.api.helpers import api_settings, mod
from tests.api.insight_helpers import V1, build_minigt, data_of, patch_evaluate, rows_of

URL = f"{V1}/metrics/detections"
ORDER = [
    ("RULE", "STRUCTURING"),
    ("RULE", "RAPID_MOVEMENT"),
    ("RULE", "HIGH_VELOCITY"),
    ("RULE", "FAN_IN"),
    ("RULE", "FAN_OUT"),
    ("RULE", "DORMANT_REACTIVATION"),
    ("NETWORK", "NET_SHARED_ATTRIBUTE"),
    ("NETWORK", "NET_CYCLE"),
    ("NETWORK", "NET_HUB"),
]
COUNTS = ("alerts", "true_positives", "false_positives", "scenarios", "detected")
STRUCTURING = {
    "source": "RULE",
    "detection": "STRUCTURING",
    "baseline": False,
    "target_typology": "structuring",
    "alerts": 1,
    "true_positives": 1,
    "false_positives": 0,
    "fp_rate": 0.0,
    "precision": 1.0,
    "recall": 1.0,
    "scenarios": 1,
    "detected": 1,
}
FUZZY = {
    "source": "SCREENING",
    "detection": "fuzzy",
    "baseline": True,
    "target_typology": None,
    "alerts": 4436,
    "true_positives": 25,
    "false_positives": 4411,
    "fp_rate": 0.9944,
    "precision": 0.0056,
    "recall": 1.0,
    "scenarios": 25,
    "detected": 25,
}


def _by(rows: list[dict[str, Any]], detection: str) -> dict[str, Any]:
    (row,) = [r for r in rows if r["detection"] == detection]
    return row


def _get(duck: Any, client: Any) -> Any:
    build_minigt(duck)
    r = client(user="analyst01").get(URL)
    assert r.status_code == 200, r.text
    return r


def test_ac8_http_equals_function_and_feature(duck: Any, client: Any) -> None:
    r = _get(duck, client)
    assert r.json()["feature"] == "metrics_detections"
    assert r.json()["data"] == mod("aml.metrics").detections(duck, api_settings())


def test_ac8_nine_rows_in_order(duck: Any, client: Any) -> None:
    rows = _get(duck, client).json()["data"]["rows"]
    assert [(r["source"], r["detection"]) for r in rows] == ORDER


def test_ac8_structuring_row(duck: Any, client: Any) -> None:
    rows = _get(duck, client).json()["data"]["rows"]
    assert _by(rows, "STRUCTURING") == STRUCTURING


def test_ac8_other_measured_rows(duck: Any, client: Any) -> None:
    rows = _get(duck, client).json()["data"]["rows"]
    rapid = _by(rows, "RAPID_MOVEMENT")
    assert (rapid["alerts"], rapid["true_positives"], rapid["false_positives"]) == (1, 0, 1)
    assert rapid["fp_rate"] == 1.0
    assert rapid["precision"] == 0.0
    assert rapid["recall"] is None
    assert rapid["scenarios"] == 0
    hv = _by(rows, "HIGH_VELOCITY")
    assert hv["alerts"] == 0
    for key in ("fp_rate", "precision", "recall", "scenarios", "target_typology"):
        assert hv[key] is None, key
    fan_out = _by(rows, "FAN_OUT")
    assert fan_out["true_positives"] == 1
    assert fan_out["fp_rate"] == 0.0
    cycle = _by(rows, "NET_CYCLE")
    assert (cycle["alerts"], cycle["true_positives"], cycle["false_positives"]) == (1, 0, 1)
    assert cycle["recall"] == 0.0
    assert (cycle["scenarios"], cycle["detected"]) == (1, 0)


def test_ac8_counts_are_int_and_nothing_is_nan(duck: Any, client: Any) -> None:
    build_minigt(duck)
    for data in (
        data_of(client(user="analyst01").get(URL)),
        mod("aml.metrics").detections(duck, api_settings()),
    ):
        assert data["rows"]
        for row in data["rows"]:
            for key in COUNTS:
                assert row[key] is None or type(row[key]) is int, (row["detection"], key)
            for value in row.values():
                assert not (isinstance(value, float) and math.isnan(value))


def test_ac8_screening_unavailable_without_a_watchlist(duck: Any, client: Any) -> None:
    data = _get(duck, client).json()["data"]
    assert data["unavailable"] == [
        {"part": "screening", "message": "watchlist is empty; run `aml load` first"}
    ]


def test_ac8_screening_rows_from_evaluate(
    duck: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_minigt(duck)
    c = client(user="analyst01")
    patch_evaluate(monkeypatch)
    data = data_of(c.get(URL))
    rows = data["rows"]
    assert len(rows) == 13
    assert [r["source"] for r in rows[-4:]] == ["SCREENING"] * 4
    assert [r["detection"] for r in rows[-4:]] == ["exact", "fuzzy", "two_tier_alert", "two_tier"]
    assert _by(rows, "fuzzy") == FUZZY
    two = _by(rows, "two_tier")
    assert two["baseline"] is False
    assert two["alerts"] == 72
    assert two["false_positives"] == 47
    assert two["fp_rate"] == 0.6528
    assert data["unavailable"] == []
    assert data == mod("aml.metrics").detections(duck, api_settings())


def test_ac8_schema_gives_six_idle_rule_rows(schema: Any, client: Any) -> None:
    r = client(user="analyst01").get(URL)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data["rows"]) == 6
    assert all(row["source"] == "RULE" and row["alerts"] == 0 for row in data["rows"])
    assert data["unavailable"] == [
        {"part": "network", "message": "no network run yet; run `aml network` first"},
        {"part": "screening", "message": "customers is empty; run `aml load` first"},
    ]


def test_ac8_get_changes_no_row(duck: Any, client: Any) -> None:
    build_minigt(duck)
    before = rows_of(duck)
    assert client(user="analyst01").get(URL).status_code == 200
    assert rows_of(duck) == before
