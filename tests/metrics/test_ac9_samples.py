"""AC9 of specs/ui-mock-pages.md: auto-cleared sample and suppression panels."""

from __future__ import annotations

import json
from typing import Any

from tests.api.helpers import api_settings, mod
from tests.api.insight_helpers import V1, build_minigt, build_minis, data_of, rows_of
from tests.api.live_helpers import assert_error
from tests.cases.prio_helpers import insert_truth

AUTO = f"{V1}/metrics/below-the-line/auto-cleared"
SUPP = f"{V1}/metrics/suppression"
PEP_TRUTH = [
    ("GT-PEP-0001", "pep_hit", True, "customer", "C06", "subject"),
    ("GT-PEP-0001", "pep_hit", True, "watchlist_entry", "WL3", "listed_entry"),
]
AUTO_MINIGT = {
    "population": 1,
    "ground_truth_available": True,
    "true_hits_in_population": 0,
    "seed": 42,
    "sample_size": 1,
    "true_hits_in_sample": 0,
    "sample": [
        {
            "cif": "C06",
            "entry_id": "WL3",
            "list_type": "PEP",
            "final_score": 60.0,
            "reason": "test reason",
            "truth": "NOT_A_HIT",
        }
    ],
}
S2_REASON = (
    "good-guy list: C05 x WL2 cleared on 2026-06-30 by analyst01 (case C-C05-20260630); "
    "valid until 2027-06-30; customer and watchlist entry unchanged"
)
S2_SAMPLE = {
    "item_key": "SCREENING|C05|WL2",
    "golden_customer_id": "G-C05",
    "source": "SCREENING",
    "rule_id": "SCREENING_REVIEW",
    "suppression_rule": "GOOD_GUY",
    "suppression_reason": S2_REASON,
    "truth": None,
}


def _auto(client: Any, query: str = "") -> Any:
    return client(user="analyst01").get(AUTO + query)


def _add_cleared(duck: Any) -> None:
    for i in range(1, 31):
        duck.execute(
            "INSERT INTO screening_results (run_id, cif, entry_id, list_type, matched_name, "
            "matched_name_type, token_set, jaro_winkler, fuzzy_score, coverage, name_score, "
            "final_score, decision, reason, superseded_by) VALUES (1, ?, 'WL9', 'PEP', "
            "'LISTED NAME', 'PRIMARY', 1.0, 1.0, 1.0, 1.0, 1.0, 55.0, 'AUTO_CLEARED', "
            "'test reason', NULL)",
            [f"X{i:02d}"],
        )


# ---------------------------------------------------------------- auto-cleared
def test_ac9_auto_cleared_on_minigt(duck: Any, client: Any) -> None:
    build_minigt(duck)
    r = _auto(client)
    assert r.status_code == 200, r.text
    assert r.json()["feature"] == "metrics_auto_cleared"
    assert r.json()["data"] == AUTO_MINIGT


def test_ac9_auto_cleared_equals_function(duck: Any, client: Any) -> None:
    build_minigt(duck)
    expected = mod("aml.metrics").auto_cleared_sample(duck, api_settings())
    assert data_of(_auto(client)) == json.loads(json.dumps(expected))


def test_ac9_auto_cleared_size_is_validated(duck: Any, client: Any) -> None:
    build_minigt(duck)
    assert_error(_auto(client, "?size=0"), 422, "invalid_request")
    assert_error(_auto(client, "?size=201"), 422, "invalid_request")


def test_ac9_auto_cleared_true_hit(duck: Any, client: Any) -> None:
    build_minigt(duck)
    insert_truth(duck, PEP_TRUTH)
    data = data_of(_auto(client))
    assert data["true_hits_in_population"] == 1
    assert data["sample"][0]["truth"] == "TRUE_HIT"


def test_ac9_auto_cleared_without_ground_truth(api_mini: Any, client: Any) -> None:
    data = data_of(_auto(client))
    assert data["ground_truth_available"] is False
    assert data["true_hits_in_population"] is None
    assert data["true_hits_in_sample"] is None
    assert all(row["truth"] is None for row in data["sample"])


def test_ac9_auto_cleared_seeded_sample(duck: Any, client: Any) -> None:
    build_minigt(duck)
    _add_cleared(duck)
    first = _auto(client, "?size=5")
    data = first.json()["data"]
    assert data["population"] == 31
    assert [r["cif"] for r in data["sample"]] == ["X02", "X13", "X18", "X21", "X30"]
    assert _auto(client, "?size=5").content == first.content


def test_ac9_auto_cleared_seed_comes_from_settings(duck: Any, client: Any) -> None:
    build_minigt(duck)
    r = client(user="analyst01", AML__SEED="7").get(AUTO)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["seed"] == 7


# ---------------------------------------------------------------- suppression
def test_ac9_suppression_on_minigt_is_empty(duck: Any, client: Any) -> None:
    build_minigt(duck)
    r = client(user="analyst01").get(SUPP)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["feature"] == "metrics_suppression"
    data = body["data"]
    assert data["population"] == 0
    assert data["sample"] == []
    assert data["by_rule"] == {"GOOD_GUY": 0, "HIBERNATION": 0}
    assert data["suspicious_suppressed"] == 0


def test_ac9_suppression_on_mini_s(duck: Any, client: Any) -> None:
    build_minis(duck)
    data = data_of(client(user="analyst01").get(SUPP))
    assert data["case_run"] == {"run_id": 2, "as_of": "2026-06-30"}
    assert data["stage"] == mod("aml.metrics").funnel(duck, api_settings())["stages"][1]
    assert data["stage"]["tool"] == "suppression"
    assert data["by_rule"] == {"GOOD_GUY": 1, "HIBERNATION": 0}
    assert data["population"] == 1
    assert data["ground_truth_available"] is False
    assert data["suspicious_suppressed"] is None
    assert data["sample"] == [S2_SAMPLE]


def test_ac9_suppression_invariant(duck: Any, client: Any) -> None:
    build_minis(duck)
    data = data_of(client(user="analyst01").get(SUPP))
    assert data["population"] == data["stage"]["removed"]
    assert data["population"] == data["by_rule"]["GOOD_GUY"] + data["by_rule"]["HIBERNATION"]


def test_ac9_suppression_with_ground_truth(duck: Any, client: Any) -> None:
    build_minis(duck)
    insert_truth(duck)
    data = data_of(client(user="analyst01").get(SUPP))
    assert data["ground_truth_available"] is True
    assert data["suspicious_suppressed"] == 1
    assert data["sample"][0]["truth"] == "SUSPICIOUS"


def test_ac9_suppression_size_is_validated(duck: Any, client: Any) -> None:
    build_minis(duck)
    assert_error(client(user="analyst01").get(SUPP + "?size=0"), 422, "invalid_request")
    assert_error(client(user="analyst01").get(SUPP + "?size=201"), 422, "invalid_request")


def test_ac9_suppression_on_schema(schema: Any, client: Any) -> None:
    r = client(user="analyst01").get(SUPP)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["case_run"] is None
    assert data["by_rule"] is None
    assert data["population"] == 0
    assert data["unavailable"] == [
        {"part": "suppression", "message": "no case run yet: run `aml cases build` first"}
    ]


def test_ac9_get_changes_no_row(duck: Any, client: Any) -> None:
    build_minigt(duck)
    before = rows_of(duck)
    c = client(user="analyst01")
    for url in (AUTO, AUTO + "?size=5", SUPP):
        assert c.get(url).status_code == 200, url
    assert client(user="supervisor01").get(SUPP).status_code == 200
    assert rows_of(duck) == before
