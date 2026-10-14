"""AC3 of specs/ui-mock-pages.md: GET /api/v1/cases/{case_id}/summary (template, never an LLM)."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from tests.assistant.an_helpers import LLM, RaisingLLM
from tests.cases.helpers import query

from .helpers import api_settings, mod
from .insight_helpers import C1, C5, NOPE, V1, fakes, rows_of
from .live_helpers import assert_error, audit_total

URL = f"{V1}/cases/{C1}/summary"
CITATIONS = [
    "STRUCTURING|A01|2026-03-02T09:00:00",
    "NET_CYCLE|A01>A03>A04|2026-03-05T10:00:00",
    "RAPID_MOVEMENT|A02|2026-04-20T08:00:00",
]
HEAD = (
    "# Case C-C01-20260302\n\n> TEMPLATE SUMMARY (summary/v1): generated from stored case data "
    "without an LLM. It is not a disposition.\n"
)


def _expected(db: Any) -> dict[str, Any]:
    nar = mod("aml.cases.narrative")
    data = dataclasses.asdict(nar.summarize(db, api_settings(), C1))
    data["citations"] = list(data["citations"])
    return data


def test_ac3_data_equals_summarize_and_meta_masked(api_mini: Any, client: Any) -> None:
    r = client(user="analyst01").get(URL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "live"
    assert body["feature"] == "case_summary"
    assert body["meta"] == {"pii": "masked"}
    assert body["data"] == _expected(api_mini)


def test_ac3_measured_values(api_mini: Any, client: Any) -> None:
    r = client(user="analyst01").get(URL)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    nar = mod("aml.cases.narrative")
    assert data["generator"] == "template"
    assert data["version"] == "summary/v1"
    assert data["language"] == "en"
    assert data["watermark"] == nar.TEMPLATE_WATERMARK
    assert data["citations"] == CITATIONS
    assert data["markdown"].startswith(HEAD)
    assert "| C01 | Nguyen T. C. |" in data["markdown"]


def test_ac3_markdown_never_holds_the_real_name(api_mini: Any, client: Any) -> None:
    name = query(api_mini, "SELECT full_name FROM customers WHERE cif = 'C01'").iloc[0, 0]
    r = client(user="analyst01").get(URL)
    assert r.status_code == 200, r.text
    assert name not in r.json()["data"]["markdown"]


def test_ac3_supervisor_same_body_masked_no_audit(api_mini: Any, client: Any) -> None:
    before = audit_total(api_mini)
    a = client(user="analyst01").get(URL)
    s = client(user="supervisor01").get(URL)
    assert a.status_code == 200 and s.status_code == 200
    assert s.json() == a.json()
    assert s.json()["meta"]["pii"] == "masked"
    assert audit_total(api_mini) == before


def test_ac3_language_en_same_and_vi_is_422(api_mini: Any, client: Any) -> None:
    c = client(user="analyst01")
    default = c.get(URL)
    assert default.status_code == 200, default.text
    assert c.get(URL + "?language=en").json()["data"] == default.json()["data"]
    r = c.get(URL + "?language=vi")
    assert_error(r, 422, "invalid_request")
    assert (
        r.json()["error"]["message"] == "language 'vi' is not available in the template generator"
    )


def test_ac3_screening_only_case(api_mini: Any, client: Any) -> None:
    r = client(user="analyst01").get(f"{V1}/cases/{C5}/summary")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["citations"] == ["SCREENING|C05|WL2"]


def test_ac3_unknown_case_is_404(api_mini: Any, client: Any) -> None:
    assert_error(
        client(user="analyst01").get(f"{V1}/cases/{NOPE}/summary"),
        404,
        "not_found",
        "unknown case_id",
    )


def test_ac3_config_generator_llm_is_ignored(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = RaisingLLM(AssertionError("the summary endpoint must not call the model"))
    fakes(monkeypatch, llm=fake)
    r = client(user="analyst01", AML__CASES__SUMMARY__GENERATOR="llm").get(URL)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["generator"] == "template"
    assert fake.calls == []


def test_ac3_rows_unchanged_by_every_call(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch, llm=LLM())
    before = rows_of(api_mini)
    c = client(user="analyst01")
    for suffix, status in (("", 200), ("?language=en", 200), ("?language=vi", 422)):
        assert c.get(URL + suffix).status_code == status, suffix
    assert c.get(f"{V1}/cases/{C5}/summary").status_code == 200
    assert c.get(f"{V1}/cases/{NOPE}/summary").status_code == 404
    assert client(user="supervisor01").get(URL).status_code == 200
    assert rows_of(api_mini) == before
