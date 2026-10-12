"""AC4-AC6 for specs/entity-resolution.md: `run_er` on TINY, weights, audit and re-runs."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb
from tests.dba.conftest import audit_rows

from .helpers import (
    AS_OF,
    MATCH_REASON_95_253,
    duck_settings,
    er_audit,
    load_tiny_duck,
    mod,
    pair_row,
    pairs_of,
    query,
    r2,
    run_er,
    scalar,
    truth_pairs,
)


@pytest.fixture(scope="module")
def once(
    tiny_parquet: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[DuckDb, Settings, Any]]:
    """TINY with exactly one run_er (read-only for the tests of this module)."""
    db = load_tiny_duck(tiny_parquet, tmp_path_factory.mktemp("er_once") / "tiny.duckdb")
    settings = duck_settings()
    run = run_er(db, settings)
    yield db, settings, run
    db.close()


@pytest.fixture
def tiny(tiny_parquet: Path, tmp_path: Path) -> Iterator[tuple[DuckDb, Settings]]:
    db = load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb")
    yield db, duck_settings()
    db.close()


def test_ac4_run_counts(once: tuple[DuckDb, Settings, Any]) -> None:
    _, _, run = once
    assert run.run_id == 1
    assert run.as_of == AS_OF
    assert run.customers_resolved == 300
    assert run.blocked_pairs == 53
    assert (run.match_pairs, run.review_pairs) == (32, 0)
    assert (run.clusters, run.merged_clusters, run.merged_cifs) == (273, 22, 49)


def test_ac4_er_runs_row(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, run = once
    df = query(db, "SELECT * FROM er_runs")
    assert len(df) == 1
    row = df.iloc[0]
    assert int(row["run_id"]) == 1
    assert str(row["as_of"])[:10] == "2026-06-30"
    for field in (
        "customers_resolved",
        "blocked_pairs",
        "match_pairs",
        "review_pairs",
        "clusters",
        "merged_clusters",
        "merged_cifs",
    ):
        assert int(row[field]) == getattr(run, field), field
    assert row["version"] == "er/v1"
    assert float(row["match_threshold"]) == 0.95
    assert float(row["review_threshold"]) == 0.5
    assert round(float(row["prior_probability"]), 6) == 0.000793
    assert str(row["splink_version"]).startswith("5.")
    assert re.fullmatch(r"[0-9a-f]{16}", str(row["config_hash"]))


def test_ac4_golden_ids(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    gold = query(db, "SELECT * FROM er_golden WHERE run_id = 1")
    assert len(gold) == 300
    assert gold["golden_customer_id"].nunique() == 273
    sizes = gold["cluster_size"].astype(int).value_counts().to_dict()
    assert sizes == {1: 251, 2: 34, 3: 15}
    by_cif = gold.set_index("cif")
    for cif in ("CIF00000047", "CIF00000138", "CIF00000268"):
        assert by_cif.loc[cif, "golden_customer_id"] == "G-CIF00000047"
    for cif in ("CIF00000095", "CIF00000253"):
        assert by_cif.loc[cif, "golden_customer_id"] == "G-CIF00000095"
    assert by_cif.loc["CIF00000001", "golden_customer_id"] == "G-CIF00000001"
    assert int(by_cif.loc["CIF00000001", "cluster_size"]) == 1

    view = query(db, "SELECT cif, golden_customer_id, cluster_size FROM customer_golden")
    assert len(view) == 300
    want = {(r.cif, r.golden_customer_id, int(r.cluster_size)) for r in gold.itertuples()}
    assert {(r.cif, r.golden_customer_id, int(r.cluster_size)) for r in view.itertuples()} == want


def test_ac4_pairs_are_the_true_duplicates(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    pairs = pairs_of(db, 1)
    assert len(pairs) == 32
    assert set(pairs["decision"]) == {"MATCH"}
    assert (pairs["cif_l"] < pairs["cif_r"]).all()
    assert (pairs["match_probability"].astype(float) >= 0.9999).all()
    assert set(zip(pairs["cif_l"], pairs["cif_r"], strict=True)) == truth_pairs(db)


def test_ac5_pair_weights_and_reason(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    pairs = pairs_of(db, 1)
    row = pair_row(pairs, "CIF00000095", "CIF00000253")
    got = {
        c: r2(row[c])
        for c in (
            "match_weight",
            "mw_prior",
            "mw_name",
            "mw_dob",
            "mw_phone",
            "mw_email",
            "mw_address",
            "mw_id",
        )
    }
    assert got == {
        "match_weight": 24.36,
        "mw_prior": -10.30,
        "mw_name": 6.40,
        "mw_dob": 10.31,
        "mw_phone": 9.57,
        "mw_email": -0.86,
        "mw_address": 9.24,
        "mw_id": 0.00,
    }
    assert row["reason"] == MATCH_REASON_95_253

    future = pair_row(pairs, "CIF00000134", "CIF00000277")
    assert (r2(future["mw_dob"]), r2(future["mw_id"]), r2(future["match_weight"])) == (
        0.00,
        10.28,
        26.69,
    )
    same_email = pair_row(pairs, "CIF00000005", "CIF00000285")
    assert (r2(same_email["match_weight"]), r2(same_email["mw_email"])) == (48.46, 10.60)
    typo = pair_row(pairs, "CIF00000110", "CIF00000244")
    assert (r2(typo["mw_name"]), r2(typo["match_weight"])) == (1.59, 29.82)


def test_ac5_weights_add_up(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    pairs = pairs_of(db, 1)
    cols = ["mw_name", "mw_dob", "mw_phone", "mw_email", "mw_address", "mw_id"]
    total = pairs["mw_prior"].astype(float) + pairs[cols].astype(float).sum(axis=1)
    assert ((total - pairs["match_weight"].astype(float)).abs() <= 0.001).all()


def test_ac5_model_table(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    model = query(db, "SELECT * FROM er_model WHERE run_id = 1")
    assert len(model) == 21
    assert model.groupby("comparison").size().to_dict() == {
        "name": 5,
        "address": 4,
        "dob": 3,
        "phone": 3,
        "email": 3,
        "id": 3,
    }
    nulls = model[model["level_no"].astype(int) == 0]
    assert len(nulls) == 6
    assert all(bool(v) for v in nulls["is_null_level"])
    assert nulls["match_weight"].isna().all()

    def level(comparison: str, no: int) -> Any:
        sel = model[(model["comparison"] == comparison) & (model["level_no"].astype(int) == no)]
        assert len(sel) == 1
        return sel.iloc[0]

    dob1 = level("dob", 1)
    assert float(dob1["m_probability"]) == 0.97
    assert round(float(dob1["u_probability"]), 6) == 0.000766
    assert r2(dob1["match_weight"]) == 10.31
    assert r2(level("dob", 2)["match_weight"]) == -5.06
    assert r2(level("id", 2)["match_weight"]) == -5.64


def test_ac5_cluster_weights_view(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    view = query(db, "SELECT * FROM er_cluster_weights")
    assert len(view) == 22
    sel = view[view["golden_customer_id"] == "G-CIF00000047"]
    assert len(sel) == 1
    row = sel.iloc[0]
    assert int(row["cluster_size"]) == 3
    assert int(row["pairs"]) == 3
    assert r2(row["min_match_weight"]) == 37.00
    assert r2(row["avg_match_weight"]) == 40.82
    assert r2(row["avg_mw_email"]) == 2.96
    assert r2(row["avg_mw_id"]) == 10.28


def test_ac5_explain_cluster(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    runner = mod("aml.entity_resolution.runner")
    df = runner.explain_cluster(db, "G-CIF00000047")
    df.columns = [c.lower() for c in df.columns]
    assert list(zip(df["cif_l"], df["cif_r"], strict=True)) == [
        ("CIF00000047", "CIF00000138"),
        ("CIF00000047", "CIF00000268"),
        ("CIF00000138", "CIF00000268"),
    ]
    assert [r2(w) for w in df["match_weight"]] == [37.00, 48.46, 37.00]
    assert len(runner.explain_cluster(db, "G-CIF00000001")) == 0
    with pytest.raises(runner.ErError, match="unknown golden_customer_id"):
        runner.explain_cluster(db, "G-NOPE")


def test_ac6_first_run_audit(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    audit = er_audit(db)
    assert len(audit) == 23
    merged = audit[audit["entity_type"] == "golden_customer"]
    assert len(merged) == 22
    assert set(merged["decision"]) == {"MERGED"}
    assert set(audit["version"]) == {"er/v1"}
    runs = audit[audit["entity_type"] == "er_run"]
    assert len(runs) == 1
    assert (runs.iloc[0]["entity_id"], runs.iloc[0]["decision"]) == ("1", "ER_RUN_COMPLETED")
    assert set(audit["entity_type"]) == {"golden_customer", "er_run"}

    rows = audit_rows(db, "module = 'entity_resolution'")
    done = rows[rows["entity_type"] == "er_run"].iloc[0]["details"]
    assert done["match_pairs"] == 32
    assert done["review_pairs"] == 0
    assert done["clusters"] == 273
    assert done["merged_clusters"] == 22

    one = merged[merged["entity_id"] == "G-CIF00000047"]
    assert len(one) == 1
    assert one.iloc[0]["reason"] == (
        "linked 3 CIFs (CIF00000047, CIF00000138, CIF00000268) by 3 MATCH pair(s); "
        "weakest link CIF00000047-CIF00000138 weight 37.00"
    )
    det = rows[rows["entity_id"] == "G-CIF00000047"].iloc[0]["details"]
    assert det["run_id"] == 1
    assert det["cifs"] == ["CIF00000047", "CIF00000138", "CIF00000268"]
    assert det["pairs"] == 3
    assert not (merged["entity_id"] == "G-CIF00000001").any()


def _snapshot(db: DuckDb, run_id: int) -> tuple[set[Any], set[Any]]:
    gold = query(
        db,
        f"SELECT cif, golden_customer_id, cluster_size FROM er_golden WHERE run_id = {run_id}",
    )
    pairs = pairs_of(db, run_id)
    return (
        {(r.cif, r.golden_customer_id, int(r.cluster_size)) for r in gold.itertuples()},
        {
            (
                r.cif_l,
                r.cif_r,
                round(float(r.match_weight), 4),
                round(float(r.match_probability), 6),
                r.decision,
                r.reason,
            )
            for r in pairs.itertuples()
        },
    )


def test_ac6_reruns_append_and_are_deterministic(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    first = run_er(db, settings)
    audit_after_first = len(er_audit(db))
    assert audit_after_first == 23
    second = run_er(db, settings)
    assert len(er_audit(db)) == audit_after_first + 23
    third = run_er(db, duck_settings(AML__SEED="7"))
    assert len(er_audit(db)) == audit_after_first + 46

    assert (second.run_id, third.run_id) == (2, 3)
    assert dataclasses.replace(second, run_id=1) == first
    assert dataclasses.replace(third, run_id=1) == first

    for run_id in (1, 2, 3):
        assert scalar(db, f"SELECT COUNT(*) FROM er_golden WHERE run_id = {run_id}") == 300
        assert scalar(db, f"SELECT COUNT(*) FROM er_pairs WHERE run_id = {run_id}") == 32
        assert scalar(db, f"SELECT COUNT(*) FROM er_model WHERE run_id = {run_id}") == 21
    base = _snapshot(db, 1)
    assert _snapshot(db, 2) == base
    assert _snapshot(db, 3) == base

    view = query(db, "SELECT cif, golden_customer_id, cluster_size FROM customer_golden")
    assert len(view) == 300
    assert {(r.cif, r.golden_customer_id, int(r.cluster_size)) for r in view.itertuples()} == (
        _snapshot(db, 3)[0]
    )
