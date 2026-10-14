"""AC7 of specs/ui-mock-pages.md: GET /api/v1/metrics/funnel and ``aml.metrics.funnel``."""

from __future__ import annotations

from typing import Any

import pytest

from tests.api.helpers import api_settings, mod
from tests.api.insight_helpers import (
    V1,
    build_minigt,
    build_minis,
    data_of,
    patch_evaluate,
    rows_of,
)
from tests.cases.helpers import record_disposition

URL = f"{V1}/metrics/funnel"
NULL_STAGE = {
    "before": None,
    "after": None,
    "removed": None,
    "reduction_pct": None,
    "hours_saved": None,
}
SUPPRESSION_0 = {
    "tool": "suppression",
    "before_label": "alert items",
    "after_label": "active alert items",
    "before": 9,
    "after": 9,
    "removed": 0,
    "reduction_pct": 0.0,
    "hours_saved": 0.0,
}
CONSOLIDATION = {
    "tool": "consolidation",
    "before_label": "active alert items",
    "after_label": "cases",
    "before": 9,
    "after": 5,
    "removed": 4,
    "reduction_pct": 44.44,
    "hours_saved": 1.0,
}
SCREENING_STAGE = {
    "tool": "screening_tuning",
    "before_label": "fuzzy baseline pairs",
    "after_label": "two-tier ALERT + REVIEW pairs",
    "before": 4436,
    "after": 72,
    "removed": 4364,
    "reduction_pct": 98.38,
    "hours_saved": 1091.0,
}


def _stage(data: dict[str, Any], tool: str) -> dict[str, Any]:
    (stage,) = [s for s in data["stages"] if s["tool"] == tool]
    return stage


def test_ac7_minigt_http_equals_function(duck: Any, client: Any) -> None:
    build_minigt(duck)
    r = client(user="analyst01").get(URL)
    assert r.status_code == 200, r.text
    assert r.json()["feature"] == "metrics_funnel"
    assert r.json()["data"] == mod("aml.metrics").funnel(duck, api_settings())


def test_ac7_minigt_stages_and_run(duck: Any, client: Any) -> None:
    build_minigt(duck)
    data = data_of(client(user="analyst01").get(URL))
    assert data["case_run"] == {"run_id": 1, "as_of": "2026-06-30"}
    assert data["minutes_per_alert"] == 15
    assert [s["tool"] for s in data["stages"]] == [
        "screening_tuning",
        "suppression",
        "consolidation",
    ]
    assert _stage(data, "suppression") == SUPPRESSION_0
    assert _stage(data, "consolidation") == CONSOLIDATION
    assert {
        k: v for k, v in _stage(data, "screening_tuning").items() if k in NULL_STAGE
    } == NULL_STAGE
    assert data["unavailable"] == [
        {"part": "screening_tuning", "message": "watchlist is empty; run `aml load` first"}
    ]
    assert data["total_hours_saved"] == 1.0


def test_ac7_minigt_conversion_before_any_decision(duck: Any, client: Any) -> None:
    build_minigt(duck)
    conv = data_of(client(user="analyst01").get(URL))["conversion"]
    assert conv["alert_to_case"] == {"alerts": 7, "items": 9, "cases": 5, "cases_per_alert": 0.7143}
    cts = conv["case_to_suspicious"]
    assert cts["decided"] == 0
    assert cts["rate"] is None
    zero = {"decided": 0, "suspicious": 0, "false_positive": 0}
    assert cts["by_origin"] == {"HUMAN": zero, "SIMULATED": zero}


def test_ac7_minutes_per_alert_is_configurable(duck: Any, client: Any) -> None:
    build_minigt(duck)
    data = data_of(client(user="analyst01", AML__METRICS__MINUTES_PER_ALERT="30").get(URL))
    assert data["minutes_per_alert"] == 30
    assert _stage(data, "consolidation")["hours_saved"] == 2.0


def test_ac7_conversion_after_human_and_simulated_decisions(duck: Any, client: Any) -> None:
    build_minigt(duck)
    r = client(user="analyst01").post(
        f"{V1}/cases/C-C05-20260630/disposition",
        json={"disposition": "FALSE_POSITIVE", "reason": "name only match"},
    )
    assert r.status_code == 201, r.text
    record_disposition(
        duck,
        api_settings(),
        "C-C03-20260305",
        "SUSPICIOUS",
        reason="sim",
        actor="simulated_analyst",
        origin="SIMULATED",
    )
    data = data_of(client(user="analyst01").get(URL))
    assert data["conversion"]["case_to_suspicious"] == {
        "decided": 2,
        "suspicious": 1,
        "false_positive": 1,
        "rate": 0.5,
        "by_origin": {
            "HUMAN": {"decided": 1, "suspicious": 0, "false_positive": 1},
            "SIMULATED": {"decided": 1, "suspicious": 1, "false_positive": 0},
        },
    }
    assert data == mod("aml.metrics").funnel(duck, api_settings())


def test_ac7_mini_s_counts_with_suppression(duck: Any, client: Any) -> None:
    build_minis(duck)
    data = data_of(client(user="analyst01").get(URL))
    sup, con = _stage(data, "suppression"), _stage(data, "consolidation")
    assert (sup["before"], sup["after"], sup["removed"]) == (11, 10, 1)
    assert sup["reduction_pct"] == 9.09
    assert sup["hours_saved"] == 0.2
    assert (con["before"], con["after"], con["removed"]) == (10, 4, 6)
    assert con["reduction_pct"] == 60.0
    assert con["hours_saved"] == 1.5


def test_ac7_screening_stage_from_evaluate(
    duck: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_minigt(duck)
    c = client(user="analyst01")
    patch_evaluate(monkeypatch)
    data = data_of(c.get(URL))
    assert _stage(data, "screening_tuning") == SCREENING_STAGE
    assert data == mod("aml.metrics").funnel(duck, api_settings())


def test_ac7_schema_has_nothing_to_measure(schema: Any, client: Any) -> None:
    r = client(user="analyst01").get(URL)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["case_run"] is None
    for stage in data["stages"]:
        assert {k: stage[k] for k in NULL_STAGE} == NULL_STAGE
    assert data["total_hours_saved"] is None
    assert data["conversion"]["alert_to_case"] == {
        "alerts": None,
        "items": None,
        "cases": None,
        "cases_per_alert": None,
    }
    assert data["unavailable"] == [
        {"part": "screening_tuning", "message": "customers is empty; run `aml load` first"},
        {"part": "suppression", "message": "no case run yet: run `aml cases build` first"},
        {"part": "consolidation", "message": "no case run yet: run `aml cases build` first"},
    ]


def test_ac7_get_changes_no_row(duck: Any, client: Any) -> None:
    build_minigt(duck)
    before = rows_of(duck)
    c = client(user="analyst01")
    assert c.get(URL).status_code == 200
    assert client(user="supervisor01").get(URL).status_code == 200
    mod("aml.metrics").funnel(duck, api_settings())
    assert rows_of(duck) == before
