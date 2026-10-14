"""Does every audit row that carries a model's output also carry the model's version?

A reviewer who finds a score or a label in the audit trail must be able to tell which model
produced it. `MODEL_DECISIONS` lists the audit decisions that hold such output; `version_gaps`
reads them and reports every row whose version is missing or names no known model. The audit trail
is append-only, so an old row with a gap is reported, never corrected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from aml.cases.values import lower_columns
from aml.common.db import Database
from aml.memo.normalize import MEMO_VERSION

__all__ = [
    "MODEL_DECISIONS",
    "ModelDecision",
    "VersionGap",
    "check_versions",
    "json_text",
    "table_exists",
    "version_gaps",
]

ML_ANOMALY_RULE = "ML_ANOMALY"
ALERT_PREFIX = "ML_ANOMALY/"  # version of an anomaly ALERT row: ML_ANOMALY/<model_version>
MISSING_VERSION, UNKNOWN_VERSION, MISSING_MODEL = (
    "missing version",
    "unknown version",
    "missing details.model",
)


@dataclass(frozen=True)
class ModelDecision:
    module: str
    decision: str
    registry: str  # "case_models" | "memo" | "anomaly_runs" | "screening_ml_models"
    rule_id: str | None = None  # only rows whose details.rule_id is this (the anomaly ALERT rows)


@dataclass(frozen=True)
class VersionGap:
    module: str
    decision: str
    entity_id: str
    event_ts: datetime
    problem: str  # "missing version" | "unknown version" | "missing details.model"


MODEL_DECISIONS: tuple[ModelDecision, ...] = (
    ModelDecision("cases", "PRIORITIZED", "case_models"),
    ModelDecision("cases", "MODEL_TRAINED", "case_models"),
    ModelDecision("cases", "SCORING_RUN_COMPLETED", "case_models"),
    ModelDecision("cases", "BTL_EVALUATED", "case_models"),
    ModelDecision("memo", "MEMO_CLASSIFIED", "memo"),
    ModelDecision("memo", "MEMO_EVAL_COMPLETED", "memo"),
    ModelDecision("monitoring", "ALERT", "anomaly_runs", ML_ANOMALY_RULE),
    ModelDecision("ml_anomaly", "ANOMALY_RUN_COMPLETED", "anomaly_runs"),
    ModelDecision("screening_ml", "MODEL_TRAINED", "screening_ml_models"),
    ModelDecision("screening_ml", "ML_SCORED", "screening_ml_models"),
    ModelDecision("screening_ml", "ML_SCORING_COMPLETED", "screening_ml_models"),
)

_REGISTRY = {  # registry -> (table, version column)
    "case_models": ("case_models", "version"),
    "anomaly_runs": ("anomaly_runs", "model_version"),
    "screening_ml_models": ("screening_ml_models", "version"),
}


def table_exists(db: Database, name: str) -> bool:
    """True when the table exists (the tables of a sibling spec may not be there yet)."""
    if db.backend == "oracle":
        sql = f"SELECT COUNT(*) FROM user_tables WHERE table_name = '{name.upper()}'"
    else:
        sql = f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{name}'"
    return int(db.query_df(sql).iloc[0, 0]) > 0


def json_text(db: Database, path: str, column: str = "details") -> str:
    """SQL expression for one top-level key of a JSON column as text (NULL when missing)."""
    if db.backend == "oracle":
        return f"JSON_VALUE({column}, '$.{path}')"
    return f"json_extract_string({column}, '$.{path}')"


def _known_versions(db: Database, d: ModelDecision) -> set[str] | None:
    """The versions the registry of a decision knows; None when its table does not exist yet."""
    if d.registry == "memo":
        return {MEMO_VERSION}
    table, column = _REGISTRY[d.registry]
    if not table_exists(db, table):
        return None
    df = db.query_df(f"SELECT {column} FROM {table}")
    versions = {str(v) for v in df.iloc[:, 0]}
    return {ALERT_PREFIX + v for v in versions} if d.decision == "ALERT" else versions


def _rows(db: Database, d: ModelDecision, since: datetime | None) -> pd.DataFrame:
    model = f", {json_text(db, 'model')} AS model" if d.registry == "memo" else ""
    where = f"module = '{d.module}' AND decision = '{d.decision}'"
    if d.rule_id:
        where += f" AND {json_text(db, 'rule_id')} = '{d.rule_id}'"
    if since is not None:
        stamp = since.astimezone(UTC).replace(tzinfo=None) if since.tzinfo else since
        where += f" AND event_ts >= TIMESTAMP '{stamp.isoformat(sep=' ')}'"
    return lower_columns(
        db.query_df(
            f"SELECT audit_id, entity_id, event_ts, version{model} FROM audit_log "
            f"WHERE {where} ORDER BY audit_id"
        )
    )


def _problem(d: ModelDecision, row: object, known: set[str]) -> str | None:
    version = getattr(row, "version", None)
    if version is None or pd.isna(version) or str(version) == "":
        return MISSING_VERSION
    if str(version) not in known:
        return UNKNOWN_VERSION
    if d.registry == "memo":
        model = getattr(row, "model", None)
        if model is None or pd.isna(model) or str(model) == "":
            return MISSING_MODEL
    return None


def check_versions(db: Database, *, since: datetime | None = None) -> tuple[int, list[VersionGap]]:
    """``(rows checked, gaps)`` over every decision in `MODEL_DECISIONS`, in that order."""
    checked, gaps = 0, []
    for d in MODEL_DECISIONS:
        known = _known_versions(db, d)
        if known is None:
            continue
        for row in _rows(db, d, since).itertuples():
            checked += 1
            if problem := _problem(d, row, known):
                gaps.append(
                    VersionGap(
                        d.module,
                        d.decision,
                        str(row.entity_id),
                        pd.Timestamp(row.event_ts).to_pydatetime(),
                        problem,
                    )
                )
    return checked, gaps


def version_gaps(db: Database, *, since: datetime | None = None) -> list[VersionGap]:
    """The audit rows of model decisions whose version is missing or unknown."""
    return check_versions(db, since=since)[1]
