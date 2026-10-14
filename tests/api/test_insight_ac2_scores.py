"""AC2 of specs/ui-mock-pages.md: GET /api/v1/cases/scores."""

from __future__ import annotations

from typing import Any

from tests.cases.helpers import load_case

from .helpers import api_settings, mod
from .insight_helpers import R5, V1, data_of, insert_scores, rows_of, score_rows, scored

URL = f"{V1}/cases/scores"
ORDER = [
    ("C-C03-20260305", 0.912345, 1),
    ("C-C01-20260302", 0.8, 2),
    ("C-C04-20260305", 0.8, 3),
    ("C-C05-20260630", 0.2, 4),
    ("C-C01-20260531", 0.1, 5),
]
FIRST = {
    "case_id": "C-C03-20260305",
    "score": 0.912345,
    "queue_rank": 1,
    "model_version": "prio/logreg/1",
    "top_features": [
        {"feature": "network_alerts", "value": 1.0, "contribution": 1.5},
        {"feature": "alerts", "value": 2.0, "contribution": 0.4},
    ],
}
EMPTY_RUN2 = {
    "run_id": 2,
    "score_run_id": None,
    "model_version": None,
    "queue": 0,
    "scores": [],
}


def test_ac2_both_roles_get_identical_bytes_and_envelope(api_mini: Any, client: Any) -> None:
    scored(api_mini)
    a = client(user="analyst01").get(URL)
    s = client(user="supervisor01").get(URL)
    assert a.status_code == 200 and s.status_code == 200
    assert a.content == s.content
    body = a.json()
    assert body["feature"] == "case_scores"
    assert body["meta"] == {}
    data = body["data"]
    assert data["run_id"] == 1
    assert data["score_run_id"] == 1
    assert data["model_version"] == "prio/logreg/1"
    assert data["queue"] == 5


def test_ac2_order_and_first_element(api_mini: Any, client: Any) -> None:
    scored(api_mini)
    data = data_of(client(user="analyst01").get(URL))
    assert [(s["case_id"], s["score"], s["queue_rank"]) for s in data["scores"]] == ORDER
    assert data["scores"][0] == FIRST


def test_ac2_each_element_equals_load_case_score(api_mini: Any, client: Any) -> None:
    scored(api_mini)
    data = data_of(client(user="analyst01").get(URL))
    assert len(data["scores"]) == len(R5)
    for s in data["scores"]:
        assert s == {"case_id": s["case_id"], **load_case(api_mini, s["case_id"]).score}


def test_ac2_read_only(api_mini: Any, client: Any) -> None:
    scored(api_mini)
    before = rows_of(api_mini)
    assert client(user="analyst01").get(URL).status_code == 200
    assert client(user="supervisor01").get(URL).status_code == 200
    assert rows_of(api_mini) == before


def test_ac2_second_scoring_run_wins_and_unranked_goes_last(api_mini: Any, client: Any) -> None:
    scored(api_mini)
    rows = score_rows()
    for r in rows:
        if r["case_id"] == "C-C05-20260630":
            r["score"], r["queue_rank"] = 0.95, None
        if r["case_id"] == "C-C01-20260531":
            r["queue_rank"] = 4
    insert_scores(api_mini, score_run_id=2, rows=rows)
    data = data_of(client(user="analyst01").get(URL))
    assert data["score_run_id"] == 2
    assert data["queue"] == 4
    assert data["scores"][-1]["case_id"] == "C-C05-20260630"
    assert data["scores"][-1]["queue_rank"] is None


def test_ac2_new_case_run_makes_scores_empty(api_mini: Any, client: Any) -> None:
    scored(api_mini)
    mod("aml.cases.runner").run_cases(api_mini, api_settings())
    data = data_of(client(user="analyst01").get(URL))
    assert data == EMPTY_RUN2


def test_ac2_schema_has_no_run(schema: Any, client: Any) -> None:
    r = client(user="analyst01").get(URL)
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {
        "run_id": None,
        "score_run_id": None,
        "model_version": None,
        "queue": 0,
        "scores": [],
    }
