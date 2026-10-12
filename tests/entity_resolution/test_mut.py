"""AC7-AC8 for specs/entity-resolution.md: the MUT scenarios (M1-M4) and the evaluation."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb

from .helpers import (
    apply_mut,
    duck_settings,
    er_audit,
    has_pair,
    load_tiny_duck,
    mod,
    pair_row,
    pairs_of,
    query,
    r2,
    run_er,
    scalar,
)

EVAL_COLUMNS = ["level", "predicted", "truth", "tp", "fp", "fn", "precision", "recall"]


@pytest.fixture
def tiny(tiny_parquet: Path, tmp_path: Path) -> Iterator[tuple[DuckDb, Settings]]:
    db = load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb")
    yield db, duck_settings()
    db.close()


@pytest.fixture
def mutated(tiny: tuple[DuckDb, Settings]) -> tuple[DuckDb, Settings, Any, int]:
    """Run 1 on TINY, then MUT, then run 2. The last item is the audit count after run 1."""
    db, settings = tiny
    run_er(db, settings)
    audit_before = len(er_audit(db))
    apply_mut(db)
    run2 = run_er(db, settings)
    return db, settings, run2, audit_before


def _golden(db: DuckDb) -> Any:
    df = query(db, "SELECT cif, golden_customer_id, cluster_size FROM customer_golden")
    return df.set_index("cif")


def test_ac7_run_counts(mutated: tuple[DuckDb, Settings, Any, int]) -> None:
    _, _, run, _ = mutated
    assert run.run_id == 2
    assert run.customers_resolved == 302
    assert run.blocked_pairs == 55
    assert (run.match_pairs, run.review_pairs) == (32, 1)
    assert (run.clusters, run.merged_clusters) == (275, 22)


def test_ac7_pairs_after_mut(mutated: tuple[DuckDb, Settings, Any, int]) -> None:
    db, _, _, _ = mutated
    pairs = pairs_of(db, 2)

    m1 = pair_row(pairs, "CIF00000186", "CIF00000233")
    assert m1["decision"] == "MATCH"
    assert (r2(m1["mw_phone"]), r2(m1["mw_id"]), r2(m1["match_weight"])) == (-3.32, 10.29, 24.00)

    m2 = pair_row(pairs, "CIF00000095", "CIF90000001")
    assert m2["decision"] == "REVIEW"
    assert 0.75 <= float(m2["match_probability"]) <= 0.77
    assert (r2(m2["match_weight"]), r2(m2["mw_id"])) == (1.64, 0.00)
    assert m2["reason"].startswith("match probability 0.75")
    assert "< 0.95" in m2["reason"]
    assert not has_pair(pairs, "CIF00000253", "CIF90000001")

    assert not has_pair(pairs, "CIF00000006", "CIF00000119")

    m3 = pair_row(pairs, "CIF00000002", "CIF90000002")
    assert m3["decision"] == "MATCH"
    assert round(float(m3["match_probability"]), 3) == 0.998
    assert (r2(m3["match_weight"]), r2(m3["mw_dob"]), r2(m3["mw_id"])) == (8.99, -5.06, 0.00)


def test_ac7_customer_golden_after_mut(mutated: tuple[DuckDb, Settings, Any, int]) -> None:
    db, _, _, _ = mutated
    gold = _golden(db)
    assert len(gold) == 302

    def g(cif: str) -> tuple[str, int]:
        return gold.loc[cif, "golden_customer_id"], int(gold.loc[cif, "cluster_size"])

    assert g("CIF90000001") == ("G-CIF90000001", 1)
    assert g("CIF00000095") == ("G-CIF00000095", 2)
    assert g("CIF00000253") == ("G-CIF00000095", 2)
    assert g("CIF00000002")[0] == "G-CIF00000002"
    assert g("CIF90000002")[0] == "G-CIF00000002"
    assert g("CIF00000006") == ("G-CIF00000006", 1)
    assert g("CIF00000119") == ("G-CIF00000119", 1)


def test_ac7_audit_and_history(mutated: tuple[DuckDb, Settings, Any, int]) -> None:
    db, _, _, before = mutated
    audit = er_audit(db)
    new = audit.iloc[before:]
    assert len(new) == 24
    assert (new["decision"] == "MERGED").sum() == 22
    review = new[new["decision"] == "REVIEW"]
    assert len(review) == 1
    row = review.iloc[0]
    assert (row["entity_type"], row["entity_id"]) == ("er_pair", "CIF00000095:CIF90000001")
    pair = pair_row(pairs_of(db, 2), "CIF00000095", "CIF90000001")
    assert row["reason"] == pair["reason"]
    done = new[new["decision"] == "ER_RUN_COMPLETED"]
    assert len(done) == 1
    assert (done.iloc[0]["entity_type"], done.iloc[0]["entity_id"]) == ("er_run", "2")
    assert scalar(db, "SELECT COUNT(*) FROM er_golden WHERE run_id = 1") == 300
    assert scalar(db, "SELECT COUNT(*) FROM er_pairs WHERE run_id = 1") == 32


def test_ac8_evaluation_clean_tiny(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    run_er(db, settings)
    df = mod("aml.entity_resolution.evaluate").evaluate_er(db)
    df.columns = [c.lower() for c in df.columns]
    assert list(df.columns) == EVAL_COLUMNS
    assert list(df["level"]) == ["pairwise", "cluster"]
    rows = [tuple(df.iloc[i][c] for c in EVAL_COLUMNS[1:]) for i in range(2)]
    assert rows[0] == (32, 32, 32, 0, 0, 1.0, 1.0)
    assert rows[1] == (22, 22, 22, 0, 0, 1.0, 1.0)


def test_ac8_evaluation_after_mut(mutated: tuple[DuckDb, Settings, Any, int]) -> None:
    db, _, _, _ = mutated
    df = mod("aml.entity_resolution.evaluate").evaluate_er(db)
    df.columns = [c.lower() for c in df.columns]
    assert list(df["level"]) == ["pairwise", "cluster"]
    rows = [tuple(df.iloc[i][c] for c in EVAL_COLUMNS[1:]) for i in range(2)]
    assert rows[0] == (32, 32, 31, 1, 1, 0.9688, 0.9688)
    assert rows[1] == (22, 22, 21, 1, 1, 0.9545, 0.9545)


def test_ac8_evaluation_requires_a_run(tiny: tuple[DuckDb, Settings]) -> None:
    db, _ = tiny
    with pytest.raises(mod("aml.entity_resolution.runner").ErError, match="run `aml er` first"):
        mod("aml.entity_resolution.evaluate").evaluate_er(db)
