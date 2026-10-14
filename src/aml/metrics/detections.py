"""Detection quality per rule / network rule / screening method, in one row shape."""

from __future__ import annotations

from typing import Any

import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.network import evaluate as network_eval
from aml.graph.network.inputs import NetworkError
from aml.metrics.common import clean
from aml.monitoring import evaluate as rules_eval
from aml.screening import evaluate as screening_eval
from aml.screening.matching import ScreeningError

BASELINES = ("exact", "fuzzy")


def _int(value: Any) -> int:
    value = clean(value)
    return 0 if value is None else int(value)


def _opt_int(value: Any) -> int | None:
    value = clean(value)
    return None if value is None else int(value)


def _row(**fields: Any) -> dict[str, Any]:
    alerts, fp = fields["alerts"], fields["false_positives"]
    return {**fields, "fp_rate": round(fp / alerts, 4) if alerts else None}


def _rule_rows(source: str, table: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        _row(
            source=source,
            detection=str(rec["rule_id"]),
            baseline=False,
            target_typology=clean(rec["target_typology"]),
            alerts=_int(rec["alerts"]),
            true_positives=_int(rec["target_hits"]) + _int(rec["other_suspicious"]),
            false_positives=_int(rec["benign"]) + _int(rec["unlabelled"]),
            precision=clean(rec["precision_suspicious"]),
            recall=clean(rec["recall"]),
            scenarios=_opt_int(rec["scenarios"]),
            detected=_opt_int(rec["detected"]),
        )
        for rec in table.to_dict("records")
    ]


def _screening_rows(table: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        _row(
            source="SCREENING",
            detection=str(rec["method"]),
            baseline=rec["method"] in BASELINES,
            target_typology=None,
            alerts=_int(rec["flagged"]),
            true_positives=_int(rec["tp"]),
            false_positives=_int(rec["fp"]),
            precision=clean(rec["precision"]),
            recall=clean(rec["recall"]),
            scenarios=_int(rec["tp"]) + _int(rec["fn"]),
            detected=_int(rec["tp"]),
        )
        for rec in table.to_dict("records")
    ]


def detections(db: Database, settings: Settings) -> dict[str, Any]:
    rows = _rule_rows("RULE", rules_eval.evaluate_rules(db))
    unavailable: list[dict[str, str]] = []
    try:
        rows += _rule_rows("NETWORK", network_eval.evaluate_network(db))
    except NetworkError as exc:
        unavailable.append({"part": "network", "message": str(exc)})
    try:
        rows += _screening_rows(screening_eval.evaluate(db, settings))
    except ScreeningError as exc:
        unavailable.append({"part": "screening", "message": str(exc)})
    return {"rows": rows, "unavailable": unavailable}
