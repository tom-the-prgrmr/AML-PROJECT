"""AC2 for specs/screening-tiers-eval.md: Tier 1 blocking (`candidate_name_pairs`)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .helpers import BASE, base_stats, mod, norm, screening_cfg
from .helpers_3b import load_tiny_duck, query

LIST_NAMES = [
    "TRAN HUU LONG",
    "NGUYEN VAN BASHIROV",
    "NGUYEN VAN",
    "SON DO XUAN",
    "MUHAMMAD AL RASHID",
]


def test_ac2_blocking_on_base_names_gives_exactly_five_pairs() -> None:
    cfg = screening_cfg().model_copy(update={"rare_token_max_df_rate": 0.25})
    stats = base_stats(cfg)
    customers = [norm(n, cfg) for n in BASE]
    pairs = mod("aml.screening.candidates").candidate_name_pairs(customers, LIST_NAMES, stats, cfg)
    assert set(pairs) == {
        ("TRAN VAN LONG", "TRAN HUU LONG"),
        ("TRAN HUU LONG", "TRAN HUU LONG"),
        ("NGUYEN VAN AN", "NGUYEN VAN"),
        ("NGUYEN VAN BINH", "NGUYEN VAN"),
        ("DO XUAN SON", "SON DO XUAN"),
    }


def test_ac2_blocking_on_tiny_keeps_every_true_hit_and_stays_small(
    tiny_parquet: Path, tmp_path: Path
) -> None:
    cfg = screening_cfg()
    db = load_tiny_duck(tiny_parquet, tmp_path / "t.duckdb")
    try:
        stats = mod("aml.screening.idf").customer_token_stats(db, cfg)
        cust = query(db, "SELECT cif, full_name FROM customers")
        wl = query(db, "SELECT entry_id, primary_name AS name FROM watchlist")
        al = query(db, "SELECT entry_id, alias_name AS name FROM watchlist_alias")
        truth = query(
            db,
            "SELECT c.entity_id AS cif, e.entity_id AS entry_id "
            "FROM ground_truth c JOIN ground_truth e ON c.scenario_id = e.scenario_id "
            "WHERE c.entity_type = 'customer' AND c.role = 'subject' "
            "AND e.entity_type = 'watchlist_entry' AND e.role = 'listed_entry' "
            "AND c.typology IN ('sanctions_hit', 'pep_hit')",
        )
    finally:
        db.close()
    normalize = mod("aml.screening.normalize").normalize_name
    cif_norm = {r.cif: normalize(r.full_name, cfg) for r in cust.itertuples()}
    entry_names: dict[str, set[str]] = defaultdict(set)
    for r in [*wl.itertuples(), *al.itertuples()]:
        n = normalize(r.name, cfg)
        if n:
            entry_names[r.entry_id].add(n)
    list_norms = {n for names in entry_names.values() for n in names}
    pairs = mod("aml.screening.candidates").candidate_name_pairs(
        set(cif_norm.values()), list_norms, stats, cfg
    )
    assert len(truth) == 5
    for r in truth.itertuples():
        assert any((cif_norm[r.cif], n) in pairs for n in entry_names[r.entry_id]), r
    by_name: dict[str, list[str]] = defaultdict(list)
    for cif, n in cif_norm.items():
        by_name[n].append(cif)
    cif_entry: set[tuple[str, str]] = set()
    for entry_id, names in entry_names.items():
        for cn, ln in pairs:
            if ln in names:
                cif_entry.update((cif, entry_id) for cif in by_name.get(cn, ()))
    assert 0 < len(cif_entry) <= 600
