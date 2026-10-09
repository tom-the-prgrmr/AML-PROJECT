"""Phase 1 orchestration: customers (1a) -> activity (1b) -> watchlist (1c) -> Parquet.

Output is one ``<table>.parquet`` per table plus a byte-deterministic ``manifest.json``.
Files are first written to a temp directory next to ``out_dir`` and then moved into place,
so a failed run never leaves a mix of old and new tables; unrelated files are left alone.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from aml.common.config import Settings
from aml.datagen.activity import GROUND_TRUTH_COLUMNS, TxnGenParams, generate_activity
from aml.datagen.customers import generate_customers_from_settings
from aml.datagen.watchlist import generate_watchlist

__all__ = ["MANIFEST_NAME", "TABLES", "Manifest", "run_pipeline"]

MANIFEST_NAME = "manifest.json"
TABLES = [
    "customers",
    "customer_person",
    "admin_unit_mapping",
    "accounts",
    "transactions",
    "ground_truth",
    "dq_labels",
    "watchlist",
    "watchlist_alias",
]


@dataclass(frozen=True)
class Manifest:
    """Describes a generated dataset (serialised as ``manifest.json``)."""

    seed: int
    profile: str
    profile_params: dict[str, object]
    start_date: str
    reference_date: str
    tables: dict[str, int]

    def to_json(self) -> str:
        """Deterministic JSON text (sorted keys, no timestamps)."""
        payload = {
            "seed": self.seed,
            "profile": self.profile,
            "profile_params": self.profile_params,
            "start_date": self.start_date,
            "reference_date": self.reference_date,
            "tables": self.tables,
        }
        return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _build_tables(settings: Settings) -> dict[str, pd.DataFrame]:
    """Run 1a, 1b and 1c and return the nine output tables."""
    data = settings.data
    seed = settings.seed
    tables = generate_customers_from_settings(settings)
    activity = generate_activity(tables, TxnGenParams.from_settings(settings), seed)
    wl = generate_watchlist(
        activity.customers,
        tables.customer_person,
        tables.dq_defects,
        activity.ground_truth,
        data.watchlist,
        seed,
        start_date=data.start_date,
    )

    ground_truth = pd.concat(
        [
            activity.ground_truth[GROUND_TRUTH_COLUMNS],
            wl.ground_truth_rows[GROUND_TRUTH_COLUMNS],
        ],
        ignore_index=True,
    )
    defects = tables.dq_defects
    dq_from_1a = pd.DataFrame(
        {
            "entity_type": "customer",
            "entity_id": defects["cif"].to_numpy(),
            "defect_type": defects["defect_type"].to_numpy(),
            "detail": pd.Series([None] * len(defects), dtype=object),
        }
    )
    dq_labels = pd.concat([activity.dq_labels, dq_from_1a], ignore_index=True)

    customers = activity.customers
    if "person_id" in customers.columns:
        customers = customers.drop(columns=["person_id"])
    return {
        "customers": customers,
        "customer_person": tables.customer_person,
        "admin_unit_mapping": tables.admin_unit_mapping,
        "accounts": activity.accounts,
        "transactions": activity.transactions,
        "ground_truth": ground_truth,
        "dq_labels": dq_labels,
        "watchlist": wl.watchlist,
        "watchlist_alias": wl.watchlist_alias,
    }


def run_pipeline(settings: Settings, out_dir: Path) -> Manifest:
    """Generate every table for ``settings`` and write them to ``out_dir``."""
    out_dir = Path(out_dir)
    frames = _build_tables(settings)
    profile = settings.data.profile
    manifest = Manifest(
        seed=settings.seed,
        profile=profile,
        profile_params=settings.data.profiles[profile].model_dump(mode="json"),
        start_date=settings.data.start_date.isoformat(),
        reference_date=settings.data.reference_date.isoformat(),
        tables={name: len(frames[name]) for name in TABLES},
    )

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.tmp-", dir=out_dir.parent))
    try:
        for name in TABLES:
            frames[name].to_parquet(tmp / f"{name}.parquet", index=False)
        (tmp / MANIFEST_NAME).write_text(manifest.to_json(), encoding="utf-8", newline="\n")
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in [f"{t}.parquet" for t in TABLES] + [MANIFEST_NAME]:
            os.replace(tmp / name, out_dir / name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return manifest
