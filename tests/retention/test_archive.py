"""Archive-writing safety and the DuckDB refusal (specs/oracle-retention.md, Q7 and Q10)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aml.common.config import load_settings
from aml.common.db import DuckDb
from aml.dba import retention


def test_existing_archive_is_never_overwritten(tmp_path: Path) -> None:
    target = tmp_path / "transactions" / "transactions_2019-03.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"precious")

    with pytest.raises(retention.RetentionError, match="archive already exists"):
        retention._write_archive(pd.DataFrame({"txn_id": ["RT1"]}), target)

    assert target.read_bytes() == b"precious"
    assert [p.name for p in target.parent.iterdir()] == [target.name]


def test_archive_roundtrip_leaves_no_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "a" / "transactions_2019-03.parquet"
    retention._write_archive(pd.DataFrame({"txn_id": ["RT1"]}), target)
    assert list(pd.read_parquet(target)["txn_id"]) == ["RT1"]
    assert [p.name for p in target.parent.iterdir()] == [target.name]


def test_purge_on_duckdb_raises_oracle_only(duck: DuckDb) -> None:
    settings = load_settings(environ={})
    with pytest.raises(retention.RetentionError, match="Oracle only"):
        retention.purge_transactions(duck, settings, dry_run=False)
