"""AC2-AC6 for specs/monitoring-rules.md: the six rules on the hand-built MINI data sets."""

from __future__ import annotations

from datetime import date
from typing import Any

from aml.common.config import Settings
from aml.common.db import DuckDb

from .helpers import (
    MINI_DOR_ACCOUNTS,
    STR_REASON_A1,
    accounts_of,
    detect,
    duck_settings,
    ids,
    load_mini,
    mini_dor,
    mini_fan,
    mini_rap,
    mini_str,
    mini_vel,
    ts,
)


def _s(**env: str) -> Settings:
    return duck_settings(**{k: v for k, v in env.items()})


def _by_account(dets: list[Any]) -> dict[str, Any]:
    return {d.account_id: d for d in dets}


# ----------------------------------------------------------------------------- AC2 STRUCTURING
def test_ac2_structuring_default(duck: DuckDb) -> None:
    load_mini(duck, mini_str())
    dets = detect(duck, _s(), ["STRUCTURING"])
    assert [(d.account_id, d.window_start) for d in dets] == [
        ("A1", ts("2026-03-01 09:00:00")),
        ("A5", ts("2026-01-05 09:00:00")),
        ("A5", ts("2026-01-21 09:00:01")),
    ]
    a1, a5_first, a5_second = dets
    assert a1.rule_id == "STRUCTURING"
    assert a1.rule_version == "v1"
    assert a1.window_end == ts("2026-03-15 08:59:59")
    assert a1.txn_ids == ("S01", "S02", "S03")
    assert a1.amount_vnd == 1139999000
    assert a1.metrics == {"deposits": 3, "total_vnd": 1139999000, "branches": 2}
    assert a1.reason == STR_REASON_A1
    assert a1.alert_key == "STRUCTURING|A1|2026-03-01T09:00:00"
    assert (a5_first.window_end, a5_first.txn_ids, a5_first.amount_vnd) == (
        ts("2026-01-07 09:00:00"),
        ("S15", "S16", "S17"),
        1095000000,
    )
    assert (a5_second.window_end, a5_second.txn_ids, a5_second.amount_vnd) == (
        ts("2026-01-23 09:00:00"),
        ("S18", "S19", "S20"),
        1095000000,
    )


def test_ac2_structuring_min_deposits_2(duck: DuckDb) -> None:
    load_mini(duck, mini_str())
    dets = detect(duck, _s(AML__MONITORING__STRUCTURING__MIN_DEPOSITS="2"), ["STRUCTURING"])
    assert len(dets) == 6
    sel = [d for d in dets if d.account_id in {"A2", "A3", "A4"}]
    assert {d.account_id: d.txn_ids for d in sel} == {
        "A2": ("S04", "S05", "S06"),
        "A3": ("S07", "S08"),
        "A4": ("S11", "S12"),
    }


def test_ac2_structuring_larger_reporting_threshold(duck: DuckDb) -> None:
    load_mini(duck, mini_str())
    dets = detect(duck, _s(AML__THRESHOLDS__LARGE_CASH_VND="410000000"), ["STRUCTURING"])
    assert len(dets) == 1
    assert dets[0].account_id == "A3"
    assert dets[0].txn_ids == ("S07", "S08", "S09")
    assert "369,000,000 to 409,999,999 VND" in dets[0].reason


def test_ac2_structuring_as_of_cutoff(duck: DuckDb) -> None:
    load_mini(duck, mini_str())
    assert detect(duck, _s(), ["STRUCTURING"], as_of=date(2026, 1, 6)) == []
    assert len(detect(duck, _s(), ["STRUCTURING"], as_of=date(2026, 1, 7))) == 1


# ----------------------------------------------------------------------------- AC3 RAPID_MOVEMENT
def test_ac3_rapid_movement_default(duck: DuckDb) -> None:
    load_mini(duck, mini_rap())
    dets = detect(duck, _s(), ["RAPID_MOVEMENT"])
    assert len(dets) == 1
    d = dets[0]
    assert d.account_id == "A1"
    assert d.window_start == ts("2026-03-01 10:00:00")
    assert d.window_end == ts("2026-03-02 09:59:59")
    assert d.txn_ids == ("R01", "R02", "R03", "R04")
    assert d.amount_vnd == 580000000
    assert d.metrics == {"in_vnd": 300000000, "out_vnd": 280000000}
    assert d.reason == (
        "received 300,000,000 VND and sent out 280,000,000 VND (93%) between "
        "2026-03-01 10:00:00 and 2026-03-02 09:59:59"
    )


def test_ac3_rapid_movement_overrides(duck: DuckDb) -> None:
    load_mini(duck, mini_rap())
    rule = ["RAPID_MOVEMENT"]
    pct = _s(AML__MONITORING__RAPID_MOVEMENT__MIN_PASS_THROUGH_PCT="0.89")
    assert accounts_of(detect(duck, pct, rule)) == {"A1", "A2"}
    window = _s(AML__MONITORING__RAPID_MOVEMENT__WINDOW_HOURS="25")
    assert accounts_of(detect(duck, window, rule)) == {"A1", "A3"}
    inflow = _s(AML__MONITORING__RAPID_MOVEMENT__MIN_INFLOW_VND="199999000")
    assert accounts_of(detect(duck, inflow, rule)) == {"A1", "A4"}


# ----------------------------------------------------------------------------- AC4 HIGH_VELOCITY
def test_ac4_high_velocity_default(duck: DuckDb) -> None:
    load_mini(duck, mini_vel())
    dets = detect(duck, _s(), ["HIGH_VELOCITY"])
    assert [d.account_id for d in dets] == ["A1", "A5"]
    a1, a5 = dets
    assert a1.window_start == ts("2026-03-01 09:00:00")
    assert a1.window_end == ts("2026-03-01 16:00:00")
    assert a1.txn_ids == ids("VA", 1, 8)
    assert a1.amount_vnd == 120000000
    assert a1.metrics == {"txns": 8, "total_vnd": 120000000}
    assert a1.reason == (
        "8 transactions totalling 120,000,000 VND between 2026-03-01 09:00:00 and "
        "2026-03-01 16:00:00 (at least 8 within 24 hours; counterparties known for 14+ days "
        "excluded)"
    )
    assert a5.window_start == ts("2026-02-01 09:00:00")
    assert a5.window_end == ts("2026-02-01 16:00:00")
    assert a5.txn_ids == ids("VE", 1, 8)


def test_ac4_high_velocity_min_txns_7_adds_a2(duck: DuckDb) -> None:
    load_mini(duck, mini_vel())
    dets = detect(duck, _s(AML__MONITORING__HIGH_VELOCITY__MIN_TXNS="7"), ["HIGH_VELOCITY"])
    assert len(dets) == 3
    assert _by_account(dets)["A2"].amount_vnd == 140000000


def test_ac4_high_velocity_known_counterparty_days(duck: DuckDb) -> None:
    load_mini(duck, mini_vel())
    longer = detect(duck, _s(AML__MONITORING__KNOWN_COUNTERPARTY_DAYS="29"), ["HIGH_VELOCITY"])
    assert [(d.account_id, d.txn_ids[0]) for d in longer] == [
        ("A1", "VA01"),
        ("A5", "VE01"),
        ("A5", "VF01"),
    ]
    assert longer[2].txn_ids == ids("VF", 1, 8)
    shorter = detect(duck, _s(AML__MONITORING__KNOWN_COUNTERPARTY_DAYS="13"), ["HIGH_VELOCITY"])
    assert [(d.account_id, d.txn_ids) for d in shorter] == [
        ("A1", ids("VA", 1, 8)),
        ("A4", ids("VD", 1, 8)),
        ("A5", ids("VE", 1, 8)),
    ]


# ----------------------------------------------------------------------------- AC5 FAN_IN / FAN_OUT
FAN = ["FAN_IN", "FAN_OUT"]


def test_ac5_fan_default(duck: DuckDb) -> None:
    load_mini(duck, mini_fan())
    dets = detect(duck, _s(), FAN)
    assert [(d.rule_id, d.account_id) for d in dets] == [("FAN_IN", "A1"), ("FAN_OUT", "A3")]
    fan_in, fan_out = dets
    assert fan_in.window_start == ts("2026-03-01 09:00:00")
    assert fan_in.window_end == ts("2026-03-08 08:59:59")
    assert fan_in.txn_ids == ids("FA", 1, 8)
    assert fan_in.amount_vnd == 120000000
    assert fan_in.metrics == {"counterparties": 8, "txns": 8, "total_vnd": 120000000}
    assert fan_in.reason == (
        "received 120,000,000 VND from 8 new senders in 8 transactions between "
        "2026-03-01 09:00:00 and 2026-03-08 08:59:59 (at least 8 within 7 days)"
    )
    assert fan_out.window_start == ts("2026-03-10 09:00:00")
    assert fan_out.window_end == ts("2026-03-10 16:00:00")
    assert fan_out.txn_ids == ids("FC", 1, 8)
    assert fan_out.amount_vnd == 160000000
    assert fan_out.reason == (
        "sent 160,000,000 VND to 8 new receivers in 8 transactions between "
        "2026-03-10 09:00:00 and 2026-03-10 16:00:00 (at least 8 within 7 days)"
    )


def test_ac5_fan_min_counterparties_7_adds_fan_in_a2(duck: DuckDb) -> None:
    load_mini(duck, mini_fan())
    dets = detect(duck, _s(AML__MONITORING__FAN_IN_OUT__MIN_COUNTERPARTIES="7"), FAN)
    assert [(d.rule_id, d.account_id) for d in dets] == [
        ("FAN_IN", "A1"),
        ("FAN_IN", "A2"),
        ("FAN_OUT", "A3"),
    ]
    assert dets[1].metrics["counterparties"] == 7
    assert dets[1].metrics["txns"] == 8


def test_ac5_fan_known_counterparty_days(duck: DuckDb) -> None:
    load_mini(duck, mini_fan())
    short = detect(duck, _s(AML__MONITORING__KNOWN_COUNTERPARTY_DAYS="4"), FAN)
    assert len(short) == 3
    assert (short[2].rule_id, short[2].account_id, short[2].txn_ids) == (
        "FAN_OUT",
        "A5",
        ids("FE", 1, 8),
    )
    long = detect(duck, _s(AML__MONITORING__KNOWN_COUNTERPARTY_DAYS="32"), FAN)
    assert len(long) == 3
    assert (long[2].rule_id, long[2].account_id, long[2].txn_ids) == (
        "FAN_OUT",
        "A5",
        ids("FF", 1, 8),
    )


def test_ac5_fan_plus_new_receivers_alerts_only_the_new_burst(duck: DuckDb) -> None:
    load_mini(duck, mini_fan(extra_new_receivers=True))
    dets = detect(duck, _s(), FAN)
    assert len(dets) == 3
    third = dets[2]
    assert (third.rule_id, third.account_id) == ("FAN_OUT", "A5")
    assert third.window_start == ts("2026-03-05 09:30:00")
    assert third.txn_ids == ids("FH", 1, 8)
    assert third.metrics["counterparties"] == 8
    assert third.amount_vnd == 160000000


# ----------------------------------------------------------------------------- AC6 DORMANT
DOR = ["DORMANT_REACTIVATION"]


def _dor_detect(duck: DuckDb, settings: Settings, **kw: Any) -> list[Any]:
    return detect(duck, settings, DOR, **kw)


def test_ac6_dormant_default(duck: DuckDb) -> None:
    load_mini(duck, mini_dor(), MINI_DOR_ACCOUNTS)
    dets = _dor_detect(duck, _s())
    assert [d.account_id for d in dets] == ["A1", "A3"]
    a1, a3 = dets
    assert a1.window_start == ts("2026-04-10 10:00:00")
    assert a1.window_end == ts("2026-04-11 09:59:59")
    assert a1.txn_ids == ("D02", "D03")
    assert a1.amount_vnd == 110000000
    assert a1.metrics == {"quiet_days": 90, "txns": 2, "total_vnd": 110000000}
    assert a1.reason == (
        "no activity for 90 days, then 2 transaction(s) totalling 110,000,000 VND between "
        "2026-04-10 10:00:00 and 2026-04-11 09:59:59 (window 24 hours)"
    )
    assert a3.window_start == ts("2026-04-01 00:00:00")
    assert a3.txn_ids == ("D07",)
    assert a3.amount_vnd == 150000000
    assert a3.metrics["quiet_days"] == 90


def test_ac6_dormant_days_overrides(duck: DuckDb) -> None:
    load_mini(duck, mini_dor(), MINI_DOR_ACCOUNTS)
    d89 = _dor_detect(duck, _s(AML__MONITORING__DORMANT_REACTIVATION__DORMANT_DAYS="89"))
    assert accounts_of(d89) == {"A1", "A2", "A3"}
    assert _by_account(d89)["A2"].metrics["quiet_days"] == 89
    d75 = _dor_detect(duck, _s(AML__MONITORING__DORMANT_REACTIVATION__DORMANT_DAYS="75"))
    assert accounts_of(d75) == {"A1", "A2", "A3", "A4"}
    assert _by_account(d75)["A4"].metrics["quiet_days"] == 75


def test_ac6_dormant_min_amount_override(duck: DuckDb) -> None:
    load_mini(duck, mini_dor(), MINI_DOR_ACCOUNTS)
    dets = _dor_detect(duck, _s(AML__MONITORING__DORMANT_REACTIVATION__MIN_AMOUNT_VND="99999000"))
    assert accounts_of(dets) == {"A1", "A3", "A5"}
    assert _by_account(dets)["A5"].metrics["quiet_days"] == 120


def test_ac6_dormant_as_of_cutoff(duck: DuckDb) -> None:
    load_mini(duck, mini_dor(), MINI_DOR_ACCOUNTS)
    dets = _dor_detect(duck, _s(), as_of=date(2026, 4, 9))
    assert accounts_of(dets) == {"A3"}
