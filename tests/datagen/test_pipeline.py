"""Acceptance tests for specs/datagen-watchlist-output.md (AC5-AC8: pipeline, output, CLI)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from typer.testing import CliRunner

from aml.common.config import Settings, get_settings, load_settings
from aml.datagen.activity import TxnGenParams, generate_activity
from aml.datagen.customers import generate_customers_from_settings

from .conftest import TABLES, EnvFactory

HIT_TYPOLOGIES = {"sanctions_hit", "pep_hit", "screening_trap"}


def _run(settings: Settings, out: Path) -> Any:
    pipeline = importlib.import_module("aml.datagen.pipeline")
    return pipeline.run_pipeline(settings, out)


def _read(out: Path, table: str) -> pd.DataFrame:
    return pd.read_parquet(out / f"{table}.parquet")


def _cli_app() -> Any:
    return importlib.import_module("aml.cli").app


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def test_ac5_output_files_and_table_contents(tiny_settings: Settings, tmp_path: Path) -> None:
    out = tmp_path / "out5"
    _run(tiny_settings, out)
    assert {p.name for p in out.iterdir()} == {f"{t}.parquet" for t in TABLES} | {"manifest.json"}

    tables = generate_customers_from_settings(tiny_settings)
    activity = generate_activity(
        tables, TxnGenParams.from_settings(tiny_settings), tiny_settings.seed
    )
    customers = _read(out, "customers")
    assert "person_id" not in customers.columns
    assert_frame_equal(
        customers.reset_index(drop=True),
        activity.customers.reset_index(drop=True),
        check_dtype=False,
    )

    dq = _read(out, "dq_labels")
    assert len(tables.dq_defects) > 0
    assert len(dq) == len(activity.dq_labels) + len(tables.dq_defects)
    for row in tables.dq_defects.itertuples():
        match = dq[
            (dq["entity_type"] == "customer")
            & (dq["entity_id"] == row.cif)
            & (dq["defect_type"] == row.defect_type)
        ]
        assert len(match) == 1, (row.cif, row.defect_type)
        assert match["detail"].isna().all()

    gt = _read(out, "ground_truth")
    key = ["scenario_id", "typology", "entity_type", "entity_id", "role"]
    got = set(map(tuple, gt[key].astype(str).to_numpy()))
    want_1b = set(map(tuple, activity.ground_truth[key].astype(str).to_numpy()))
    assert want_1b <= got
    one_c = gt[gt["typology"].isin(HIT_TYPOLOGIES)]
    assert {"sanctions_hit", "pep_hit", "screening_trap"} & set(one_c["typology"])
    assert "screening_trap" in set(one_c["typology"])
    assert one_c["scenario_id"].nunique() == 5 + 6
    # every scenario_id belongs to exactly one typology (unique per case)
    assert (gt.groupby("scenario_id")["typology"].nunique() == 1).all()
    assert not (set(one_c["scenario_id"]) & set(activity.ground_truth["scenario_id"]))


def test_ac6_deterministic_for_same_seed_and_different_for_other_seed(
    tiny_env: EnvFactory, tmp_path: Path
) -> None:
    s42 = load_settings(environ=tiny_env())
    a, b = tmp_path / "a", tmp_path / "b"
    _run(s42, a)
    _run(s42, b)
    for t in TABLES:
        assert_frame_equal(_read(a, t), _read(b, t))
    assert (a / "manifest.json").read_bytes() == (b / "manifest.json").read_bytes()

    c = tmp_path / "c"
    _run(load_settings(environ=tiny_env(seed=43)), c)
    assert not _read(a, "watchlist").equals(_read(c, "watchlist"))


def test_ac7_watchlist_size_does_not_shift_other_tables(
    tiny_env: EnvFactory, tmp_path: Path
) -> None:
    a, b = tmp_path / "w200", tmp_path / "w300"
    _run(load_settings(environ=tiny_env(AML__DATA__WATCHLIST__ENTRIES="200")), a)
    _run(load_settings(environ=tiny_env(AML__DATA__WATCHLIST__ENTRIES="300")), b)
    assert len(_read(a, "watchlist")) == 200
    assert len(_read(b, "watchlist")) == 300
    for t in ("customers", "customer_person", "accounts", "transactions"):
        assert_frame_equal(_read(a, t), _read(b, t))


def test_ac8_cli_data_dense_profile_manifest(
    tiny_env: EnvFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env(profile="dense"))
    out = tmp_path / "dense_out"
    result = CliRunner().invoke(_cli_app(), ["data", "--out", str(out)])
    assert result.exit_code == 0, result.output
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == "dense"
    assert manifest["profile_params"]["counterparties"] == [50, 100]
    assert manifest["seed"] == 42
    assert set(manifest["tables"]) == set(TABLES)
    for t in TABLES:
        assert manifest["tables"][t] == len(_read(out, t)), t


def test_ac8_cli_data_unknown_profile_fails_and_writes_nothing(
    tiny_env: EnvFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env())
    out = tmp_path / "huge_out"
    result = CliRunner().invoke(_cli_app(), ["data", "--profile", "huge", "--out", str(out)])
    assert result.exit_code != 0
    for name in ("small", "dense", "large"):
        assert name in result.output
    assert not out.exists() or not any(out.iterdir())
