"""Load the generated Parquet dataset into the active database (DuckDB or Oracle)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from aml.common.audit import audit
from aml.common.db import Database
from aml.datagen.pipeline import TABLES

log = logging.getLogger(__name__)

CHUNK_ROWS = 50_000
DDL_SCRIPTS = ("ddl/000_audit_log.sql", "ddl/010_datagen.sql")
MANIFEST_NAME = "manifest.json"


class LoadError(RuntimeError):
    """The Parquet source directory is missing or incomplete."""


def _missing(path: Path) -> LoadError:
    return LoadError(f"Missing {path.name} in {path.parent}: run `aml data` first.")


def read_manifest(src_dir: Path) -> dict[str, Any]:
    """Validate ``src_dir`` (manifest + every listed Parquet file) and return the manifest."""
    manifest_path = src_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise _missing(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tables = manifest["tables"]
        manifest["profile"], manifest["seed"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LoadError(f"Invalid {manifest_path}: {exc!r}; run `aml data` first.") from exc
    unknown = [t for t in tables if t not in TABLES]
    if unknown:
        raise LoadError(f"Invalid {manifest_path}: unknown table(s) {unknown!r}.")
    for table in tables:
        file = src_dir / f"{table}.parquet"
        if not file.is_file():
            raise _missing(file)
    return manifest  # type: ignore[no-any-return]


def _clean(chunk: pd.DataFrame) -> pd.DataFrame:
    """Replace pd.NA / NaT / NaN with None (object dtype) for drivers that can't take them."""
    return chunk.astype(object).where(chunk.notna(), None)


def load_parquet(db: Database, src_dir: Path) -> dict[str, int]:
    """Replace the contents of all dataset tables from ``src_dir``; return rows per table.

    Validation happens before the database is touched. Re-running yields identical state.
    """
    manifest = read_manifest(Path(src_dir))
    src = Path(src_dir)
    tables: list[str] = list(manifest["tables"])

    for script in DDL_SCRIPTS:
        db.run_named_script(script)
    for table in tables:
        db.execute(f"DELETE FROM {table}")

    counts: dict[str, int] = {}
    for table in tables:
        df = pd.read_parquet(src / f"{table}.parquet")
        total = 0
        for start in range(0, len(df), CHUNK_ROWS):
            chunk = df.iloc[start : start + CHUNK_ROWS]
            if db.backend != "duckdb":
                chunk = _clean(chunk)
            total += db.insert_df(table, chunk)
        counts[table] = total
        log.info("loaded %s: %d rows", table, total)

    grand = sum(counts.values())
    audit(
        db,
        module="datagen",
        entity_type="dataset",
        entity_id=f"{manifest['profile']}-seed{manifest['seed']}",
        decision="LOADED",
        reason=f"Loaded {len(counts)} tables ({grand} rows) into {db.backend}",
        version="ddl/010",
        details={"tables": counts},
    )
    return counts
