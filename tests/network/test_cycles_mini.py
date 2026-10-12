"""AC3-AC4 for specs/network-detections.md: NET_CYCLE on MINI-CYC."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from aml.common.db import DuckDb

from .helpers import (
    cfg,
    count,
    detect,
    duck_settings,
    jd,
    network_error,
    of_rule,
    run_network,
    ts,
)

RULE = "NET_CYCLE"
B = "B1>B2>B3"
FIRST_REASON = (
    "100,000,000 VND left B1 and 90,000,000 VND (90%) returned after 3 transfers across "
    "3 customers in 48 hours (B1 -> B2 -> B3 -> B1) between "
    "2026-03-01 10:00:00 and 2026-03-03 10:00:00"
)
SECOND_REASON = (
    "80,000,000 VND left B2 and 80,000,000 VND (100%) returned after 3 transfers across "
    "3 customers in 48 hours (B2 -> B3 -> B1 -> B2) between "
    "2026-05-01 10:00:00 and 2026-05-03 10:00:00"
)


def _run(db: DuckDb, **overrides: str) -> Any:
    return detect(db, cfg(**overrides))


def _cycles(db: DuckDb, **overrides: str) -> list[Any]:
    detections = _run(db, **overrides)
    # a MINI-CYC run has no shared-attribute cluster and no hub
    assert {a.rule_id for a in detections.alerts} <= {RULE}
    return of_rule(detections, RULE)


def _subjects(alerts: list[Any]) -> list[str]:
    return [a.subject_id for a in alerts]


# ----------------------------------------------------------------------------- AC3
def test_ac3_default_finds_only_the_b_cycle_in_two_alerts(cyc: DuckDb) -> None:
    # D: Y22 before Y21; E: 168 h = window; F: 2 hops; G: G1 and G1S share an owner;
    # H: 0.69 < 0.70; I: 49,999,000 below the floor; J: 6 hops; L: equal timestamps; M: EXT-5
    assert _subjects(_cycles(cyc)) == [B, B]


def test_ac3_window_169_adds_e_cycle(cyc: DuckDb) -> None:
    alerts = _cycles(cyc, CYCLES__WINDOW_HOURS="169")
    assert _subjects(alerts) == [B, "E1>E2>E3", B]
    e = alerts[1]
    assert e.txn_ids == ("Y31", "Y32", "Y33")
    assert jd(e.details)["hours"] == 168


def test_ac3_ratio_069_adds_h_cycle(cyc: DuckDb) -> None:
    alerts = _cycles(cyc, CYCLES__MIN_AMOUNT_RATIO="0.69")
    assert sorted(_subjects(alerts)) == [B, B, "H1>H2>H3"]
    h = next(a for a in alerts if a.subject_id == "H1>H2>H3")
    assert h.amount_vnd == 238_000_000
    assert "100,000,000 VND left H1 and 69,000,000 VND (69%) returned after 3 transfers" in h.reason


def test_ac3_amount_floor_49999000_adds_i_cycle(cyc: DuckDb) -> None:
    alerts = _cycles(cyc, CYCLES__MIN_AMOUNT_VND="49999000")
    assert sorted(_subjects(alerts)) == [B, B, "I1>I2>I3"]
    i = next(a for a in alerts if a.subject_id == "I1>I2>I3")
    assert i.amount_vnd == 164_999_000


def test_ac3_max_length_6_adds_the_six_hop_cycle(cyc: DuckDb) -> None:
    alerts = _cycles(cyc, CYCLES__MAX_LENGTH="6")
    assert sorted(_subjects(alerts)) == [B, B, "J1>J2>J3>J4>J5>J6"]
    j = next(a for a in alerts if a.subject_id == "J1>J2>J3>J4>J5>J6")
    assert j.accounts == (
        ("J1", "ORIGIN"),
        ("J2", "HOP"),
        ("J3", "HOP"),
        ("J4", "HOP"),
        ("J5", "HOP"),
        ("J6", "HOP"),
    )
    assert j.txn_ids == ("Y81", "Y82", "Y83", "Y84", "Y85", "Y86")
    details = jd(j.details)
    assert details["length"] == 6
    assert details["hours"] == 5
    assert j.window_start == ts("2026-03-01 10:00:00")
    assert j.window_end == ts("2026-03-01 15:00:00")


def test_ac3_max_length_4_still_only_the_b_cycle(cyc: DuckDb) -> None:
    assert _subjects(_cycles(cyc, CYCLES__MAX_LENGTH="4")) == [B, B]


# ----------------------------------------------------------------------------- AC4
def test_ac4_two_alerts_with_exact_fields_and_37_steps(cyc: DuckDb) -> None:
    detections = _run(cyc)
    assert detections.cycle_search_steps == 37
    first, second = of_rule(detections, RULE)

    assert first.rule_version == "v1"
    assert first.subject_type == "ACCOUNT_GROUP"
    assert first.subject_id == B
    assert first.alert_key == "NET_CYCLE|B1>B2>B3|2026-03-01T10:00:00"
    assert first.accounts == (("B1", "ORIGIN"), ("B2", "HOP"), ("B3", "HOP"))
    # the duplicate transaction Y02D gives two cycles that differ in one txn_id: one alert
    assert first.txn_ids == ("Y01", "Y02", "Y02D", "Y03")
    assert first.amount_vnd == 380_000_000
    assert first.window_start == ts("2026-03-01 10:00:00")
    assert first.window_end == ts("2026-03-03 10:00:00")
    assert jd(first.details) == {
        "length": 3,
        "origin": "B1",
        "path": ["B1", "B2", "B3"],
        "first_vnd": 100_000_000,
        "last_vnd": 90_000_000,
        "hours": 48,
        "instances": 2,
    }
    assert first.reason == FIRST_REASON

    assert second.subject_id == B
    assert second.alert_key == "NET_CYCLE|B1>B2>B3|2026-05-01T10:00:00"
    assert second.accounts == (("B1", "HOP"), ("B2", "ORIGIN"), ("B3", "HOP"))
    assert second.txn_ids == ("Y11", "Y12", "Y13")
    assert second.amount_vnd == 240_000_000
    details = jd(second.details)
    assert details["path"] == ["B2", "B3", "B1"]
    assert details["instances"] == 1
    assert second.reason == SECOND_REASON


def test_ac4_as_of_cuts_the_cycle_at_its_last_transfer(cyc: DuckDb) -> None:
    before = of_rule(detect(cyc, duck_settings(), as_of=date(2026, 3, 2)), RULE)
    assert before == []
    on_last_day = of_rule(detect(cyc, duck_settings(), as_of=date(2026, 3, 3)), RULE)
    assert len(on_last_day) == 1
    assert on_last_day[0].txn_ids == ("Y01", "Y02", "Y02D", "Y03")


def test_ac4_search_budget_of_37_steps_is_enough(cyc: DuckDb) -> None:
    alerts = _cycles(cyc, CYCLES__MAX_SEARCH_STEPS="37")
    assert len(alerts) == 2


def test_ac4_search_budget_of_36_steps_raises(cyc: DuckDb) -> None:
    with pytest.raises(network_error(), match="cycle search exceeded max_search_steps"):
        detect(cyc, cfg(CYCLES__MAX_SEARCH_STEPS="36"))


def test_ac4_run_network_over_budget_writes_nothing(cyc: DuckDb) -> None:
    with pytest.raises(network_error(), match="cycle search exceeded max_search_steps"):
        run_network(cyc, cfg(CYCLES__MAX_SEARCH_STEPS="36"))
    for table in ("alerts", "monitoring_runs", "nx_account_features"):
        assert count(cyc, table) == 0, table
    assert count(cyc, "audit_log", "WHERE module = 'monitoring'") == 0


def test_ac4_cycle_through_one_owner_is_not_a_cycle(cyc: DuckDb) -> None:
    cyc.execute("UPDATE er_golden SET golden_customer_id = 'G-C-B1' WHERE cif = 'C-B3'")
    assert _cycles(cyc) == []
