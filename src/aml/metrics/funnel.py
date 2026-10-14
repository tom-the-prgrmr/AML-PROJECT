"""The alert-reduction funnel: screening tuning, suppression, consolidation, conversions."""

from __future__ import annotations

from typing import Any

from aml.common.config import Settings
from aml.common.db import Database
from aml.metrics.common import NO_RUN, empty_stage, latest_run, read, stage
from aml.screening import evaluate as screening_eval
from aml.screening.matching import ScreeningError

SCREENING_LABELS = ("fuzzy baseline pairs", "two-tier ALERT + REVIEW pairs")
SUPPRESSION_LABELS = ("alert items", "active alert items")
CONSOLIDATION_LABELS = ("active alert items", "cases")
ORIGINS = ("HUMAN", "SIMULATED")


def suppression_stage(
    settings: Settings, run: dict[str, Any] | None
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if run is None:
        return empty_stage("suppression", SUPPRESSION_LABELS), [
            {"part": "suppression", "message": NO_RUN}
        ]
    return stage(settings, "suppression", SUPPRESSION_LABELS, run["items"], run["active"]), []


def _screening_stage(
    db: Database, settings: Settings
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    try:
        table = screening_eval.evaluate(db, settings).set_index("method")
    except ScreeningError as exc:
        return empty_stage("screening_tuning", SCREENING_LABELS), [
            {"part": "screening_tuning", "message": str(exc)}
        ]
    before, after = int(table.loc["fuzzy", "flagged"]), int(table.loc["two_tier", "flagged"])
    return stage(settings, "screening_tuning", SCREENING_LABELS, before, after), []


def _alert_to_case(db: Database, run: dict[str, Any] | None) -> dict[str, Any]:
    if run is None:
        return {"alerts": None, "items": None, "cases": None, "cases_per_alert": None}
    alerts = int(read(db, "active_alerts.sql").iloc[0]["n"])
    return {
        "alerts": alerts,
        "items": run["active"],
        "cases": run["cases"],
        "cases_per_alert": round(run["cases"] / alerts, 4) if alerts else None,
    }


def _case_to_suspicious(db: Database) -> dict[str, Any]:
    by_origin = {o: {"decided": 0, "suspicious": 0, "false_positive": 0} for o in ORIGINS}
    for _, row in read(db, "dispositions.sql").iterrows():
        bucket = by_origin.setdefault(
            str(row["origin"]), {"decided": 0, "suspicious": 0, "false_positive": 0}
        )
        n = int(row["n"])
        bucket["decided"] += n
        if row["disposition"] == "SUSPICIOUS":
            bucket["suspicious"] += n
        elif row["disposition"] == "FALSE_POSITIVE":
            bucket["false_positive"] += n
    decided = sum(b["decided"] for b in by_origin.values())
    suspicious = sum(b["suspicious"] for b in by_origin.values())
    return {
        "decided": decided,
        "suspicious": suspicious,
        "false_positive": sum(b["false_positive"] for b in by_origin.values()),
        "rate": round(suspicious / decided, 4) if decided else None,
        "by_origin": by_origin,
    }


def funnel(db: Database, settings: Settings) -> dict[str, Any]:
    run = latest_run(db)
    screening, missing_screening = _screening_stage(db, settings)
    suppression, missing_suppression = suppression_stage(settings, run)
    if run is None:
        consolidation = empty_stage("consolidation", CONSOLIDATION_LABELS)
        missing_consolidation = [{"part": "consolidation", "message": NO_RUN}]
    else:
        consolidation = stage(
            settings, "consolidation", CONSOLIDATION_LABELS, run["active"], run["cases"]
        )
        missing_consolidation = []
    stages = [screening, suppression, consolidation]
    hours = [s["hours_saved"] for s in stages if s["hours_saved"] is not None]
    return {
        "case_run": None if run is None else {"run_id": run["run_id"], "as_of": run["as_of"]},
        "minutes_per_alert": settings.metrics.minutes_per_alert,
        "stages": stages,
        "total_hours_saved": round(sum(hours), 1) if hours else None,
        "conversion": {
            "alert_to_case": _alert_to_case(db, run),
            "case_to_suspicious": _case_to_suspicious(db),
        },
        "unavailable": missing_screening + missing_suppression + missing_consolidation,
    }
