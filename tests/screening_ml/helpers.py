"""Helpers for the Phase 7b-ii tests (specs/screening-ml.md): TINY-S, TOY, PAIRS, module access."""

from __future__ import annotations

import importlib
import json
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from aml.common.config import Settings, load_settings
from aml.common.db import Database
from tests.screening.helpers import base_stats, screening_cfg

AS_OF = date(2026, 6, 30)
RANKING_ONLY_LINE = "ranking only: no screening hit was cleared or closed by the model"


def mod(name: str) -> Any:
    return importlib.import_module(name)


def settings_with(**env: str) -> Settings:
    """Default config on DuckDB; ``env`` keys are full names, such as ``AML__SEED``."""
    return load_settings(environ={"DB_BACKEND": "duckdb", **env})


def query(db: Database, sql: str) -> pd.DataFrame:
    df = db.query_df(sql)
    df.columns = [str(c).lower() for c in df.columns]
    return df


def scalar(db: Database, sql: str) -> Any:
    return query(db, sql).iloc[0, 0]


def audit_df(db: Database, where: str) -> pd.DataFrame:
    """audit_log rows (oldest first) with ``details`` parsed into a dict."""
    expr = "JSON_SERIALIZE(details)" if db.backend == "oracle" else "details"
    df = query(
        db,
        "SELECT module, entity_type, entity_id, decision, reason, version, actor, "
        f"{expr} AS details FROM audit_log WHERE {where} ORDER BY audit_id",
    )
    df["details"] = [json.loads(d) if isinstance(d, str) else d for d in df["details"]]
    return df


def snapshot(db: Database, table: str, order: str) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in db.query_df(f"SELECT * FROM {table} ORDER BY {order}").to_numpy()]


# ---- the pure-function fixtures of the spec -------------------------------------------------


def cfg25() -> Any:
    return screening_cfg().model_copy(update={"rare_token_max_df_rate": 0.25})


def identifiers(**kw: Any) -> Any:
    return mod("aml.screening.decision").Identifiers(**kw)


def C(**kw: Any) -> Any:
    base: dict[str, Any] = {"dob": date(1971, 2, 15), "dob_year": 1971, "nationality": "VN"}
    return identifiers(**{**base, **kw})


def E(year: int | None, nat: str | None = "VN", **kw: Any) -> Any:
    return identifiers(dob_year=year, nationality=nat, **kw)


def F(
    cn: str,
    ln: str,
    c: Any,
    e: Any,
    name_type: str = "PRIMARY",
    list_type: str | None = "PEP",
) -> dict[str, float]:
    cfg = cfg25()
    return mod("aml.screening.ml.features").match_features(
        cn, ln, c, e, name_type=name_type, list_type=list_type,
        stats=base_stats(cfg), cfg=cfg, as_of=AS_OF,
    )  # fmt: skip


def toy() -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """TOY of the spec: X, y, groups, rule."""
    feats = mod("aml.screening.ml.features").FEATURES
    index = [f"P{i:02d}" for i in range(40)]
    X = pd.DataFrame(0.0, index=index, columns=list(feats))
    X["name_score"] = [100.0 if i % 2 == 0 else 60.0 for i in range(40)]
    y = pd.Series([int(i % 2 == 0) for i in range(40)], index=index)
    groups = pd.Series([f"WL{i:03d}" for i in range(40)], index=index)
    rule = pd.Series(
        ["ALERT" if i % 2 == 0 or i % 5 == 0 else "AUTO_CLEARED" for i in range(40)], index=index
    )
    return X, y, groups, rule


def pairs() -> tuple[pd.Series, pd.Series, pd.Series]:
    """PAIRS of the spec: y, score, rule."""
    index = [f"p{i}" for i in range(10)]
    y = pd.Series([1, 1, 1, 0, 0, 0, 0, 0, 0, 0], index=index)
    rule = pd.Series(
        ["ALERT", "ALERT", "REVIEW", "ALERT", "ALERT", "REVIEW"] + ["AUTO_CLEARED"] * 4,
        index=index,
    )
    score = pd.Series([0.9, 0.7, 0.8, 0.5, 0.4, 0.3, 0.6, 0.2, 0.1, 0.05], index=index)
    return y, score, rule


def numpy_score(artifact: str, row: pd.Series) -> float:
    """Recompute a score from the stored artifact with NumPy alone."""
    a = json.loads(artifact)
    x = row[a["features"]].to_numpy(dtype=float)
    z = float(np.sum(np.asarray(a["coef"]) * (x - np.asarray(a["mean"])) / np.asarray(a["scale"])))
    return float(1 / (1 + np.exp(-(a["intercept"] + z))))
