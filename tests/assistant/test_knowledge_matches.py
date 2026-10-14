"""AC8 for specs/assistant-knowledge.md: `rule_typologies` and `derive_matches` on MINI-C."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from aml.common.db import DuckDb
from tests.cases.helpers import (
    CASE_C01_A,
    CASE_C01_B,
    CASE_C03,
    CASE_C04,
    CASE_C05,
    N1_KEY,
    add_r5,
    count,
    duck_settings,
    load_minic,
    mod,
    record_disposition,
    run_cases,
)

from .kn_helpers import kmatches, kmodel

EXPECTED_PAIRS = [
    (CASE_C01_A, "rapid_movement"),
    (CASE_C01_A, "round_tripping"),
    (CASE_C01_A, "structuring"),
    (CASE_C01_B, "mule_ring"),
    (CASE_C01_B, "sanctions_hit"),
    (CASE_C03, "round_tripping"),
    (CASE_C04, "round_tripping"),
    (CASE_C05, "pep_hit"),
]


@pytest.fixture
def cased(duck: DuckDb) -> DuckDb:
    """MINI-C after `run_cases` (run 1)."""
    load_minic(duck)
    run_cases(duck, duck_settings())
    return duck


def _pairs(db: DuckDb) -> list[tuple[str, str]]:
    return [(m.case_id, m.typology_id) for m in kmatches().derive_matches(db)]


def _match(db: DuckDb, case_id: str, typology: str) -> Any:
    return next(
        m
        for m in kmatches().derive_matches(db)
        if (m.case_id, m.typology_id) == (case_id, typology)
    )


def test_ac8_rule_typologies_and_screening_map() -> None:
    assert kmatches().rule_typologies() == {
        "STRUCTURING": "structuring",
        "RAPID_MOVEMENT": "rapid_movement",
        "FAN_IN": "mule_ring",
        "FAN_OUT": "mule_ring",
        "NET_SHARED_ATTRIBUTE": "mule_ring",
        "NET_CYCLE": "round_tripping",
        "NET_HUB": "mule_ring",
    }
    assert kmodel().SCREENING_LIST_TYPOLOGY == {"SANCTIONS": "sanctions_hit", "PEP": "pep_hit"}


def test_ac8_pairs_are_sorted_and_complete(cased: DuckDb) -> None:
    assert _pairs(cased) == EXPECTED_PAIRS


def test_ac8_structuring_match_has_rule_alert_evidence_and_reason(cased: DuckDb) -> None:
    m = _match(cased, CASE_C01_A, "structuring")
    assert m.rule_ids == ("STRUCTURING",)
    assert m.alert_keys == ("STRUCTURING|A01|2026-03-02T09:00:00",)
    assert m.evidence_ids == ("T01",)
    assert m.reason == "1 alert(s) from rule(s) STRUCTURING map to typology structuring"


def test_ac8_other_rule_matches(cased: DuckDb) -> None:
    assert _match(cased, CASE_C01_A, "rapid_movement").evidence_ids == ("T05", "T06")
    mule = _match(cased, CASE_C01_B, "mule_ring")
    assert mule.rule_ids == ("FAN_OUT",)
    assert mule.evidence_ids == ("T07",)
    for case_id in (CASE_C01_A, CASE_C03, CASE_C04):
        cycle = _match(cased, case_id, "round_tripping")
        assert cycle.rule_ids == ("NET_CYCLE",)
        assert cycle.alert_keys == (N1_KEY,)
        assert cycle.evidence_ids == ("T02", "T03", "T04")


def test_ac8_screening_matches_use_the_cif_entry_pair(cased: DuckDb) -> None:
    sanctions = _match(cased, CASE_C01_B, "sanctions_hit")
    assert sanctions.rule_ids == ("SCREENING_ALERT",)
    assert sanctions.alert_keys == ("SCREENING|C02|WL1",)
    assert sanctions.evidence_ids == ("C02:WL1",)
    pep = _match(cased, CASE_C05, "pep_hit")
    assert pep.rule_ids == ("SCREENING_REVIEW",)
    assert pep.evidence_ids == ("C05:WL2",)


def test_ac8_rules_without_a_target_never_appear(cased: DuckDb) -> None:
    for m in kmatches().derive_matches(cased):
        assert "DORMANT_REACTIVATION" not in m.rule_ids
        assert "HIGH_VELOCITY" not in m.rule_ids


def test_ac8_derive_matches_writes_nothing(cased: DuckDb) -> None:
    tables = ("audit_log", "cases", "case_alerts")
    before = [count(cased, t) for t in tables]
    kmatches().derive_matches(cased)
    assert [count(cased, t) for t in tables] == before


def test_ac8_a_new_alert_without_target_changes_nothing(cased: DuckDb) -> None:
    add_r5(cased)
    run_cases(cased, duck_settings())
    assert _pairs(cased) == EXPECTED_PAIRS


def test_ac8_closed_cases_keep_their_matches(cased: DuckDb) -> None:
    settings = duck_settings()
    record_disposition(
        cased,
        settings,
        CASE_C01_A,
        "FALSE_POSITIVE",
        reason="x",
        actor="analyst01",
        decided_on=date(2026, 6, 30),
    )
    run_cases(cased, settings)
    assert [p for p in _pairs(cased) if p[0] == CASE_C01_A] == EXPECTED_PAIRS[:3]


def test_ac8_without_a_case_run_there_are_no_matches(duck: DuckDb) -> None:
    mod("aml.dba.schema").apply_schema(duck)
    assert kmatches().derive_matches(duck) == []
