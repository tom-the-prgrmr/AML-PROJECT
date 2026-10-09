"""A tampered manifest must be rejected before the database is touched."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aml.datagen.load import LoadError, load_parquet


class _Db:
    backend = "duckdb"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_named_script(self, name: str) -> None:
        self.calls.append(name)

    def execute(self, sql: str, *args: Any) -> None:
        self.calls.append(sql)


@pytest.mark.parametrize("bad", ["x; DROP TABLE customers", "../evil", "unknown_table"])
def test_unknown_table_name_rejected_before_db_access(tmp_path: Path, bad: str) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"tables": ["customers", bad], "profile": "small", "seed": 1}),
        encoding="utf-8",
    )
    db = _Db()
    with pytest.raises(LoadError, match="unknown table"):
        load_parquet(db, tmp_path)  # type: ignore[arg-type]
    assert db.calls == []
