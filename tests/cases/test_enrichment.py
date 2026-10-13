"""AC4 and AC5 for specs/case-consolidation.md: enrichment sections and the graph source."""

from __future__ import annotations

import json

import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb

from .helpers import (
    CASE_C01_A,
    CASE_C01_B,
    CASE_C03,
    CASE_C04,
    CASE_C05,
    MINI_CASES,
    OFFLINE_URI,
    SECTIONS,
    add_gds_features,
    add_nx_features,
    all_keys,
    case_error,
    duck_settings,
    enrichment,
    load_case,
    query,
    run_cases,
)

PII_KEYS = {"full_name", "phone", "email", "address", "memo"}
FEATURE_KEYS = {
    "in_degree",
    "out_degree",
    "in_vnd",
    "out_vnd",
    "pagerank_ratio",
    "shared_cluster_id",
    "shared_cluster_size",
    "cycle_alerts",
    "is_hub",
    "wcc_size",
    "louvain_size",
}


def _offline(**env: str) -> Settings:
    return duck_settings(AML__NEO4J__URI=OFFLINE_URI, **env)


# ---------------------------------------------------------------- AC4
def test_ac4_every_case_has_the_six_sections(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    df = query(minic, "SELECT case_id, section FROM case_enrichment_current")
    assert len(df) == 30
    for case_id in MINI_CASES:
        assert sorted(df[df["case_id"] == case_id]["section"]) == sorted(SECTIONS), case_id


def test_ac4_kyc_and_linked_cifs(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    e = enrichment(minic, CASE_C01_A)
    assert e["kyc"]["risk_rating"] == "HIGH"
    assert [c["cif"] for c in e["kyc"]["cifs"]] == ["C01", "C02"]
    assert e["kyc"]["cifs"][0] == {
        "cif": "C01",
        "kyc_risk": "LOW",
        "occupation": "Kế toán",
        "nationality": "VN",
        "gender": "F",
        "birth_year": 1990,
        "id_type": "PASSPORT",
    }
    linked = e["linked_cifs"]
    assert linked["cluster_size"] == 2
    assert linked["cifs"] == ["C01", "C02"]
    assert [a["account_id"] for a in linked["accounts"]] == ["A01", "A02"]


def test_ac4_dq_issues(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    customer = enrichment(minic, CASE_C01_A)["dq_issues"]["customer"]
    missing = {"rule_id": "KYC_OCCUPATION_MISSING", "dimension": "COMPLETENESS"}
    assert {"cif": "C02", **missing} in customer
    assert not [x for x in customer if x["cif"] == "C01" and x["rule_id"] == missing["rule_id"]]


def test_ac4_txn_summary(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    t = enrichment(minic, CASE_C01_A)["txn_summary"]
    want = {
        "window_start": "2026-01-21",
        "window_end": "2026-04-20",
        "txn_count": 5,
        "in_count": 3,
        "out_count": 2,
        "in_vnd": 1_170_000_000,
        "out_vnd": 780_000_000,
        "cash_in_vnd": 390_000_000,
        "cash_out_vnd": 0,
        "counterparties": 4,
        "max_txn_vnd": 500_000_000,
        "active_days": 4,
    }
    for key, value in want.items():
        assert t[key] == value, key
    assert t["by_channel"] == {
        "CASH": {"count": 1, "vnd": 390_000_000},
        "EBANKING": {"count": 1, "vnd": 480_000_000},
        "INTERBANK_TRANSFER": {"count": 1, "vnd": 500_000_000},
        "INTERNAL_TRANSFER": {"count": 2, "vnd": 580_000_000},
    }


def test_ac4_network_counterparties_and_shared_cases(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    net = enrichment(minic, CASE_C01_A)["network"]
    got = [
        (c["account_id"], c["golden_customer_id"], c["direction"], c["txns"], c["vnd"])
        for c in net["counterparties"]
    ]
    assert got == [
        ("EXT-01", None, "IN", 1, 500_000_000),
        ("EXT-02", None, "OUT", 1, 480_000_000),
        ("A03", "G-C03", "OUT", 1, 300_000_000),
        ("A04", "G-C04", "IN", 1, 280_000_000),
    ]
    assert net["shared_alert_cases"] == [CASE_C03, CASE_C04]


def test_ac4_history_of_the_later_case(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    assert enrichment(minic, CASE_C01_A)["history"]["prior_cases"] == []
    e = enrichment(minic, CASE_C01_B)
    prior = e["history"]["prior_cases"]
    assert len(prior) == 1
    assert prior[0]["case_id"] == CASE_C01_A
    assert prior[0]["alerts"] == 3
    assert prior[0]["disposition"] is None
    assert e["history"]["prior_alerts"] == 3
    assert e["txn_summary"]["window_end"] == "2026-06-30"
    assert e["txn_summary"]["txn_count"] == 3


def test_ac4_case_without_transactions(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    e = enrichment(minic, CASE_C05)
    assert e["txn_summary"]["txn_count"] == 0
    assert e["txn_summary"]["in_vnd"] == 0
    assert e["txn_summary"]["by_channel"] == {}
    assert e["network"]["counterparties"] == []


def test_ac4_enrichment_holds_no_pii(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    df = query(minic, "SELECT content FROM case_enrichment_current")
    assert len(df) == 30
    for content in df["content"]:
        text = content if isinstance(content, str) else json.dumps(content)
        assert "B123456" not in text
        assert not (all_keys(json.loads(text)) & PII_KEYS)


def test_ac4_load_case_masked_and_unmasked(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    view = load_case(minic, CASE_C01_A)
    assert view.status == "OPEN"
    assert view.case_id == CASE_C01_A
    assert view.golden_customer_id == "G-C01"
    assert len(view.alerts) == 3
    assert [a.rule_id for a in view.alerts] == ["STRUCTURING", "NET_CYCLE", "RAPID_MOVEMENT"]
    assert set(view.enrichment) == set(SECTIONS)
    assert view.disposition is None
    assert view.score is None
    assert len(view.subjects) == 2
    assert all("dob" not in s for s in view.subjects)
    raw = load_case(minic, CASE_C01_A, masked=False)
    assert len(raw.subjects) == 2
    assert all("dob" in s for s in raw.subjects)


def test_ac4_load_case_unknown_id(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    with pytest.raises(case_error(), match="unknown case_id"):
        load_case(minic, "C-NOPE-20260101")


# ---------------------------------------------------------------- AC5
def test_ac5_networkx_features_are_aggregated_per_golden_customer(minic: DuckDb) -> None:
    add_nx_features(minic)
    run = run_cases(minic, _offline())
    assert run.graph_source == "networkx"
    net = enrichment(minic, CASE_C01_A)["network"]
    assert net["source"] == "networkx"
    assert net["features"] == {
        "in_degree": 2,
        "out_degree": 3,
        "in_vnd": 790_000_000,
        "out_vnd": 780_000_000,
        "pagerank_ratio": 1.8,
        "shared_cluster_id": "SHARED-C02",
        "shared_cluster_size": 5,
        "cycle_alerts": 1,
        "is_hub": 1,
        "wcc_size": None,
        "louvain_size": None,
    }


def test_ac5_auto_prefers_gds_of_the_same_as_of(minic: DuckDb) -> None:
    add_nx_features(minic)
    add_gds_features(minic)
    run = run_cases(minic, _offline())
    assert run.graph_source == "gds"
    net = enrichment(minic, CASE_C01_A)["network"]
    assert net["source"] == "gds"
    f = net["features"]
    assert (f["in_degree"], f["wcc_size"], f["louvain_size"]) == (7, 4, 3)
    assert f["cycle_alerts"] is None
    assert f["is_hub"] is None


def test_ac5_explicit_networkx_ignores_gds(minic: DuckDb) -> None:
    add_nx_features(minic)
    add_gds_features(minic)
    run = run_cases(minic, _offline(AML__CASES__GRAPH_FEATURES="networkx"))
    assert run.graph_source == "networkx"
    assert enrichment(minic, CASE_C01_A)["network"]["source"] == "networkx"


def test_ac5_auto_ignores_gds_of_another_as_of(minic: DuckDb) -> None:
    add_nx_features(minic)
    add_gds_features(minic, gds_as_of="2026-05-31")
    run = run_cases(minic, _offline())
    assert run.graph_source == "networkx"


def test_ac5_no_feature_tables_gives_source_none(minic: DuckDb) -> None:
    run = run_cases(minic, _offline())
    assert run.graph_source == "none"
    net = enrichment(minic, CASE_C01_A)["network"]
    assert net["source"] == "none"
    assert set(net["features"]) == FEATURE_KEYS
    assert all(v is None for v in net["features"].values())
    assert len(net["counterparties"]) == 4
