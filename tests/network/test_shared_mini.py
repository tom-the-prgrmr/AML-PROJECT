"""AC2 for specs/network-detections.md: NET_SHARED_ATTRIBUTE on MINI-SHR."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from aml.common.db import DuckDb

from .helpers import (
    cfg,
    detect,
    duck_settings,
    jd,
    mod,
    network_error,
    of_rule,
    subjects,
    ts,
)

RULE = "NET_SHARED_ATTRIBUTE"
C01_ACCOUNTS = (
    ("A01", "MEMBER"),
    ("A01S", "MEMBER"),
    ("A02", "MEMBER"),
    ("A03", "MEMBER"),
    ("A04", "MEMBER"),
    ("A05", "MEMBER"),
)
C01_REASON = (
    "5 customers (6 accounts) linked by shared device (4 customers), phone (2), address (2); "
    "3 transfer(s) totalling 31,000,000 VND between members between "
    "2026-03-01 10:00:00 and 2026-03-05 10:00:00"
)
C14_ACCOUNTS = tuple((f"A{n}", "MEMBER") for n in range(14, 20))
C14_REASON = (
    "6 customers (6 accounts) linked by shared device (0 customers), phone (6), address (0); "
    "no transfers between members"
)
C06_REASON = (
    "4 customers (6 accounts) linked by shared device (2 customers), phone (2), address (2); "
    "no transfers between members"
)


def _alerts(db: DuckDb, **overrides: str) -> list[Any]:
    return of_rule(detect(db, cfg(**overrides)), RULE)


def test_ac2_two_clusters_with_exact_fields(shr: DuckDb) -> None:
    alerts = _alerts(shr)
    assert [a.subject_id for a in alerts] == ["SHARED-C01", "SHARED-C14"]
    first, second = alerts

    assert first.rule_version == "v1"
    assert first.subject_type == "ACCOUNT_GROUP"
    assert first.alert_key == "NET_SHARED_ATTRIBUTE|SHARED-C01"
    assert first.accounts == C01_ACCOUNTS
    assert first.txn_ids == ("T01", "T02", "T07")
    assert first.amount_vnd == 31_000_000
    assert first.window_start == ts("2026-03-01 10:00:00")
    assert first.window_end == ts("2026-03-05 10:00:00")
    assert jd(first.details) == {
        "customers": 5,
        "cifs": ["C01", "C02", "C03", "C04", "C05"],
        "accounts": 6,
        "links": {"device": 4, "phone": 2, "address": 2},
        "shared_values": {"device": 2, "phone": 1, "address": 1},
        "internal_txns": 3,
        "internal_vnd": 31_000_000,
    }
    assert first.reason == C01_REASON

    assert second.subject_type == "ACCOUNT_GROUP"
    assert second.alert_key == "NET_SHARED_ATTRIBUTE|SHARED-C14"
    assert second.accounts == C14_ACCOUNTS  # C19 has no er_golden row but counts as a customer
    assert second.txn_ids == ()
    assert second.amount_vnd == 0
    assert second.window_start == second.window_end == ts("2026-06-30 00:00:00")
    details = jd(second.details)
    assert details["customers"] == 6
    assert details["links"] == {"device": 0, "phone": 6, "address": 0}
    assert details["cifs"] == [f"C{n}" for n in range(14, 20)]
    assert details["internal_txns"] == 0
    assert details["internal_vnd"] == 0
    assert second.reason == C14_REASON


def test_ac2_transfers_outside_the_cluster_or_of_one_owner_are_not_evidence(shr: DuckDb) -> None:
    first = _alerts(shr)[0]
    # T03 -> EXT-01, T04 -> A20 (outside), T05 same owner (A01 -> A01S), T06 after as_of
    assert {"T03", "T04", "T05", "T06"}.isdisjoint(first.txn_ids)


def test_ac2_groups_below_threshold_or_invalid_values_raise_no_alert(shr: DuckDb) -> None:
    names = subjects(detect(shr, cfg()), RULE)
    # C06..C11: 6 CIFs but 4 customers; C12/C13: 2; C20/C21: phone 12345 invalid; C22: nothing
    assert names == ["SHARED-C01", "SHARED-C14"]


def test_ac2_min_customers_4_adds_the_c06_group(shr: DuckDb) -> None:
    alerts = _alerts(shr, SHARED_ATTRIBUTES__MIN_CUSTOMERS="4")
    assert [a.subject_id for a in alerts] == ["SHARED-C01", "SHARED-C06", "SHARED-C14"]
    mid = alerts[1]
    details = jd(mid.details)
    assert details["customers"] == 4
    assert details["cifs"] == ["C06", "C07", "C08", "C09", "C10", "C11"]
    assert details["links"] == {"device": 2, "phone": 2, "address": 2}
    assert mid.accounts == tuple((f"A{n:02d}", "MEMBER") for n in range(6, 12))
    assert mid.reason == C06_REASON


def test_ac2_min_customers_6_leaves_only_c14(shr: DuckDb) -> None:
    alerts = _alerts(shr, SHARED_ATTRIBUTES__MIN_CUSTOMERS="6")
    assert [a.subject_id for a in alerts] == ["SHARED-C14"]


def test_ac2_max_customers_per_value_5_drops_the_widely_shared_phone(shr: DuckDb) -> None:
    alerts = _alerts(shr, SHARED_ATTRIBUTES__MAX_CUSTOMERS_PER_VALUE="5")
    assert [a.subject_id for a in alerts] == ["SHARED-C01"]


def test_ac2_as_of_moves_the_transaction_cutoff_only(shr: DuckDb) -> None:
    alerts = of_rule(detect(shr, duck_settings(), as_of=date(2026, 7, 1)), RULE)
    first, second = alerts
    assert first.subject_id == "SHARED-C01"
    assert first.txn_ids == ("T01", "T02", "T06", "T07")
    assert first.amount_vnd == 38_000_000
    assert first.window_end == ts("2026-07-01 10:00:00")
    assert second.subject_id == "SHARED-C14"
    assert second.window_start == ts("2026-07-01 00:00:00")


def test_ac2_without_an_er_run_detect_raises(shr: DuckDb) -> None:
    shr.execute("DELETE FROM er_runs")
    with pytest.raises(network_error(), match="run `aml er` first"):
        detect(shr, duck_settings())


def test_ac2_attribute_keys_normalise_phone_address_and_trim_device(shr: DuckDb) -> None:
    shr.execute("UPDATE customers SET device_id = '  DEV-R ' WHERE cif = 'C03'")
    customers = shr.query_df("SELECT * FROM customers")
    mapping = shr.query_df("SELECT * FROM admin_unit_mapping")
    keys = mod("aml.graph.network.shared").attribute_keys(customers, mapping)
    assert list(keys.columns) == ["cif", "device_key", "phone_key", "address_key"]
    assert list(keys["cif"]) == sorted(keys["cif"])
    by_cif = keys.set_index("cif")

    def key(cif: str, column: str) -> Any:
        value = by_cif.loc[cif, column]
        return None if value is None or value != value else value

    assert key("C01", "device_key") == "DEV-R"
    assert key("C03", "device_key") == "DEV-R"  # surrounding spaces removed
    assert key("C22", "device_key") is None  # empty string
    assert key("C02", "phone_key") == key("C01", "phone_key")  # +84 90 100 0001 == 0901000001
    assert key("C11", "phone_key") == key("C06", "phone_key")  # spaces inside the number
    assert key("C04", "address_key") == key("C01", "address_key")  # old administrative unit
    assert key("C20", "address_key") is None
    assert key("C22", "address_key") is None
