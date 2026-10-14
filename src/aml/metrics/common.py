"""Shared helpers of the metrics package: SQL loading, Stage, NaN cleaning, sampling."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database, split_oracle_script

NO_RUN = "no case run yet: run `aml cases build` first"


def sql(db: Database, name: str) -> str:
    """One statement of ``sql/<backend>/metrics/<name>`` or ``sql/common/metrics/<name>``."""
    text = db.sql_file(f"metrics/{name}").read_text(encoding="utf-8")
    if db.backend == "oracle" and "\n/" in text:
        return split_oracle_script(text)[0]
    return text.strip().rstrip(";")


def read(db: Database, name: str) -> pd.DataFrame:
    df = db.query_df(sql(db, name))
    df.columns = [str(c).lower() for c in df.columns]
    return df


def clean(value: Any) -> Any:
    """NaN / NA -> None; numpy scalars -> Python scalars."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value.item() if isinstance(value, np.generic) else value


def stage(
    settings: Settings, tool: str, labels: tuple[str, str], before: int, after: int
) -> dict[str, Any]:
    removed = before - after
    return {
        "tool": tool,
        "before_label": labels[0],
        "after_label": labels[1],
        "before": before,
        "after": after,
        "removed": removed,
        "reduction_pct": round(100 * removed / before, 2) if before else None,
        "hours_saved": round(removed * settings.metrics.minutes_per_alert / 60, 1),
    }


def empty_stage(tool: str, labels: tuple[str, str]) -> dict[str, Any]:
    return {
        "tool": tool,
        "before_label": labels[0],
        "after_label": labels[1],
        **dict.fromkeys(("before", "after", "removed", "reduction_pct", "hours_saved")),
    }


def latest_run(db: Database) -> dict[str, Any] | None:
    df = read(db, "latest_run.sql")
    if df.empty:
        return None
    row = df.iloc[0]
    return {
        "run_id": int(row["run_id"]),
        "as_of": pd.Timestamp(row["as_of"]).date().isoformat(),
        "items": int(row["items"]),
        "active": int(row["active"]),
        "cases": int(row["cases"]),
    }


def sample_indices(settings: Settings, population: int, size: int | None) -> list[int]:
    """Seeded, reproducible sample positions (sorted); an empty population gives none."""
    wanted = settings.metrics.sample_size if size is None else size
    if population == 0:
        return []
    rng = np.random.default_rng(settings.seed)
    picked = rng.choice(population, size=min(wanted, population), replace=False)
    return sorted(int(i) for i in picked)
