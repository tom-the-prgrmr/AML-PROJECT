"""Screening state written by a FULL run: fingerprints and frozen token statistics."""

from __future__ import annotations

from pathlib import Path

from aml.screening.idf import customer_token_stats
from aml.screening.matching import load_inputs
from aml.screening.runner import run_screening
from aml.screening.state import (
    customer_fingerprints,
    entry_fingerprints,
    load_token_stats,
    read_state,
)

from .helpers_3b import duck_settings, load_tiny_duck, query


def test_full_run_writes_state_and_token_stats(tiny_parquet: Path, tmp_path: Path) -> None:
    db = load_tiny_duck(tiny_parquet, tmp_path / "t.duckdb")
    settings = duck_settings()
    run_screening(db, settings)

    state = read_state(db)
    assert (len(state["customer"]), len(state["watchlist_entry"])) == (300, 200)
    ts = query(db, "SELECT token, doc_freq, n_names FROM screening_token_stats")
    assert len(ts) == 85 and set(ts["n_names"]) == {300}
    assert int(ts[ts["token"] == "NGUYEN"].iloc[0]["doc_freq"]) == 115

    stored = load_token_stats(db)
    fresh = customer_token_stats(db, settings.screening)
    assert stored is not None
    assert (stored.n_names, dict(stored.doc_freq)) == (fresh.n_names, dict(fresh.doc_freq))
    db.close()


def test_fingerprints_follow_screening_fields_only(tiny_parquet: Path, tmp_path: Path) -> None:
    db = load_tiny_duck(tiny_parquet, tmp_path / "t.duckdb")
    cfg = duck_settings().screening

    def prints() -> tuple[dict[str, str], dict[str, str]]:
        inputs = load_inputs(db)
        return customer_fingerprints(inputs, cfg), entry_fingerprints(inputs, cfg)

    base_c, base_e = prints()
    assert prints() == (base_c, base_e)  # deterministic

    db.execute("UPDATE customers SET phone = '0900000000' WHERE cif = 'CIF00000001'")
    db.execute("UPDATE watchlist SET program = 'CYBER' WHERE entry_id = 'WL000001'")
    assert prints() == (base_c, base_e)  # phone / program do not take part

    db.execute("UPDATE customers SET dob = DATE '1950-03-01' WHERE cif = 'CIF00000214'")
    db.execute(
        "INSERT INTO watchlist_alias (alias_id, entry_id, alias_name, alias_type) "
        "VALUES ('WA9000001', 'WL000001', 'TEST ALIAS', 'AKA')"
    )
    new_c, new_e = prints()
    assert [k for k in base_c if new_c[k] != base_c[k]] == ["CIF00000214"]
    assert [k for k in base_e if new_e[k] != base_e[k]] == ["WL000001"]
    db.close()
