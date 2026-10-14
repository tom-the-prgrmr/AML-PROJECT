"""Anomaly run: score every customer-month, store the scores, raise ANOMALY alerts for the top few.

Order of work: every check and every computation first (`detect_anomalies` writes nothing), then
the scores, then the alerts through the shared `record_run`, and last, in one transaction, the run
row and its audit record. `anomaly_scores_current` follows ``MAX(run_id)`` of ``anomaly_runs``, so
the scores of a run that died half way never become current. The model only raises signals for a
person to look at: nothing here closes, clears or suppresses an alert or a case.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from aml.cases.enrich_network import choose_source, load_features
from aml.cases.values import lower_columns
from aml.common.audit import AuditEvent, audit_many
from aml.common.config import Settings
from aml.common.db import Database
from aml.ml.anomaly.features import (
    ANOMALY_FEATURES,
    ANOMALY_VERSION,
    build_samples,
    feature_matrix,
)
from aml.ml.anomaly.model import (
    alert_count,
    data_hash,
    fit_score,
    iforest_params,
    library_versions,
    rank_scores,
    score_metrics,
    top_deviations,
)
from aml.monitoring.recording import AlertRecord, RuleRun, record_run

__all__ = [
    "RULE_ID",
    "SOURCE_ANOMALY",
    "AnomalyError",
    "AnomalyRun",
    "detect_anomalies",
    "run_anomaly",
]

SOURCE_ANOMALY = "ANOMALY"
RULE_ID = "ML_ANOMALY"
KIND = "isolation_forest"
ROLE_SUBJECT = "SUBJECT"
MODULE = "ml_anomaly"
LEGS_SQL = "ml/anomaly_legs.sql"


class AnomalyError(RuntimeError):
    """The anomaly model cannot run, or be evaluated, with the data it was given."""


@dataclass(frozen=True)
class AnomalyRun:
    run_id: int
    model_version: str  # f"{ANOMALY_VERSION}/{run_id}"
    as_of: date
    samples: int  # customer-months scored
    customers: int
    months: int  # distinct months with a sample
    alerts: int
    threshold: float  # score of the sample ranked `alerts` (0.0 without alerts)
    graph_source: str  # networkx | gds | none
    monitoring_run_id: int  # run_id `record_run` gave the ANOMALY alerts
    data_hash: str
    seconds: float


@dataclass(frozen=True)
class _Scored:
    """Everything computed before the first write."""

    as_of: date
    samples: pd.DataFrame  # SAMPLE_COLUMNS, ANOMALY_FEATURES, then score, rank, alerted
    legs: pd.DataFrame  # the legs the samples were built from
    graph_source: str
    data_hash: str
    alerts: int
    threshold: float
    deviations: dict[tuple[str, str], list[dict[str, Any]]]  # of the alerted samples


def _scalar(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def _check_data(db: Database) -> None:
    exists = (
        "SELECT COUNT(*) FROM user_tables WHERE table_name = 'TRANSACTIONS'"
        if db.backend == "oracle"
        else "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'transactions'"
    )
    if _scalar(db, exists) == 0:  # only a missing table; a database outage is raised as it is
        raise AnomalyError("transactions is unavailable; run `aml load` first")
    if _scalar(db, "SELECT COUNT(*) AS n FROM transactions") == 0:
        raise AnomalyError("transactions is empty; run `aml load` first")


def _read_legs(db: Database, as_of: date) -> pd.DataFrame:
    lines = db.sql_file(LEGS_SQL).read_text(encoding="utf-8").strip().splitlines()
    if lines and lines[-1].strip() == "/":
        lines = lines[:-1]
    cutoff = as_of + timedelta(days=1)
    sql = "\n".join(lines).strip().rstrip(";")
    return lower_columns(db.query_df(sql.replace("{cutoff}", f"TIMESTAMP '{cutoff} 00:00:00'")))


def _score(db: Database, settings: Settings, as_of: date) -> _Scored:
    """Build the samples, fit and score them; raises `AnomalyError` before anything is written."""
    cfg = settings.ml.anomaly
    _check_data(db)
    legs = _read_legs(db, as_of)
    source = choose_source(db, settings.cases.graph_features, as_of)
    samples = build_samples(
        legs, load_features(db, source), as_of=as_of, start_date=settings.data.start_date, cfg=cfg
    )
    if len(samples) < cfg.min_samples:
        raise AnomalyError(
            f"only {len(samples)} customer-months to learn from, "
            f"need at least ml.anomaly.min_samples={cfg.min_samples}"
        )
    X = feature_matrix(samples)
    scores = fit_score(X, cfg, seed=settings.seed)
    rank = rank_scores(scores)
    alerts = alert_count(len(X), cfg.alert_top_fraction)
    samples = samples.assign(
        score=scores.to_numpy(),
        rank=rank.to_numpy(),
        alerted=(rank <= alerts).astype(int).to_numpy(),
    )
    alerted = samples[samples["alerted"] == 1].sort_values("rank")
    threshold = float(alerted["score"].iloc[-1]) if alerts else 0.0
    deviations = {
        (r.cif, r.month): top_deviations(X, (r.cif, r.month), cfg.top_deviations)
        for r in alerted.itertuples()
    }
    return _Scored(as_of, samples, legs, source, data_hash(X), alerts, threshold, deviations)


def detect_anomalies(
    db: Database, settings: Settings, *, as_of: date | None = None
) -> pd.DataFrame:
    """Score every customer-month as of a date; one row each, with ``score``, ``rank``, ``alerted``.

    Writes nothing.
    """
    return _score(db, settings, as_of or settings.data.reference_date).samples


def _next_run_id(db: Database) -> int:
    # anomaly_scores counts too: a run that died before its anomaly_runs row must not reuse its id.
    return 1 + max(
        _scalar(db, "SELECT COALESCE(MAX(run_id), 0) FROM anomaly_runs"),
        _scalar(db, "SELECT COALESCE(MAX(run_id), 0) FROM anomaly_scores"),
    )


def _reason(row: Any, scored: _Scored, model_version: str) -> str:
    named = ", ".join(
        f"{d['feature']} {d['z']:+.2f}" for d in scored.deviations[(row.cif, row.month)]
    )
    return (
        f"anomaly score {row.score:.4f} ranks {row.rank} of {len(scored.samples)} customer-months "
        f"as of {scored.as_of.isoformat()} (alerting the top {scored.alerts}); strongest "
        f"deviations from the median: {named} (IQR units); model {model_version}; "
        "a signal for a person to review, not a finding"
    )


def _evidence(scored: _Scored, alerted: pd.DataFrame) -> dict[tuple[str, str], tuple[str, ...]]:
    """Every distinct transaction of each alerted customer-month."""
    legs = scored.legs[scored.legs["cif"].isin(alerted["cif"])]
    month = pd.to_datetime(legs["txn_ts"]).dt.strftime("%Y-%m")
    pairs = legs.assign(month=month).drop_duplicates(["cif", "month", "txn_id"])
    return {
        (str(cif), str(m)): tuple(sorted(g["txn_id"].astype(str)))
        for (cif, m), g in pairs.groupby(["cif", "month"])
    }


def _alert_records(scored: _Scored, model_version: str) -> list[AlertRecord]:
    alerted = scored.samples[scored.samples["alerted"] == 1].sort_values("rank")
    evidence = _evidence(scored, alerted)
    return [
        AlertRecord(
            rule_id=RULE_ID,
            rule_version=model_version,
            subject_type="CUSTOMER",
            subject_id=str(row.cif),
            accounts=tuple((a, ROLE_SUBJECT) for a in row.accounts),
            window_start=row.first_ts.to_pydatetime(),
            window_end=row.last_ts.to_pydatetime(),
            txn_ids=evidence[(row.cif, row.month)],
            amount_vnd=int(row.amount_vnd),
            reason=_reason(row, scored, model_version),
            details={
                "anomaly_score": float(row.score),
                "rank": int(row.rank),
                "samples": len(scored.samples),
                "alerts": scored.alerts,
                "month": row.month,
                "model_version": model_version,
                "top_deviations": scored.deviations[(row.cif, row.month)],
            },
            alert_key=f"{RULE_ID}|{row.cif}|{row.month}",
        )
        for row in alerted.itertuples()
    ]


def _score_rows(run_id: int, model_version: str, scored: _Scored) -> pd.DataFrame:
    s = scored.samples
    deviations = [
        json.dumps(scored.deviations[(c, m)]) if a else None
        for c, m, a in zip(s["cif"], s["month"], s["alerted"], strict=True)
    ]
    frame = pd.DataFrame(
        {
            "run_id": run_id,
            "cif": s["cif"].to_numpy(),
            "month": s["month"].to_numpy(),
            "model_version": model_version,
            "window_start": s["window_start"].to_numpy(),
            "window_end": s["window_end"].to_numpy(),
            "score": s["score"].to_numpy(),
            "rank": s["rank"].to_numpy(),
            "alerted": s["alerted"].to_numpy(),
        }
    )
    # Rebuilt as an object column: a column with None would otherwise become float with NaN.
    frame["top_deviations"] = pd.Series(deviations, dtype=object)
    return frame


def _run_reason(run: AnomalyRun, scored: _Scored, settings: Settings) -> str:
    cfg = settings.ml.anomaly
    months = sorted(scored.samples["month"].unique())
    return (
        f"scored {run.samples} customer-months of {run.customers} customers "
        f"({months[0]} to {months[-1]}) with isolation forest {run.model_version} "
        f"(seed {settings.seed}, {cfg.n_estimators} trees, graph features from "
        f"{run.graph_source}); {run.alerts} alert(s) at score >= {run.threshold:.4f} "
        f"(top {cfg.alert_top_fraction:.1%}); signals for review only, nothing is closed or cleared"
    )


def _run_row(
    run: AnomalyRun, scored: _Scored, settings: Settings, metrics: dict[str, float], actor: str
) -> pd.DataFrame:
    cfg = settings.ml.anomaly
    n = run.samples
    params = {
        "config": cfg.model_dump(mode="json"),
        "iforest": iforest_params(cfg, n, seed=settings.seed),
        **library_versions(),
    }
    row = {
        "run_id": run.run_id,
        "run_ts": datetime.now(UTC).replace(tzinfo=None),
        "as_of": run.as_of,
        "model_version": run.model_version,
        "kind": KIND,
        "feature_version": ANOMALY_VERSION,
        "seed": settings.seed,
        "samples": n,
        "customers": run.customers,
        "months": run.months,
        "alerts": run.alerts,
        "threshold": run.threshold,
        "graph_source": run.graph_source,
        "monitoring_run_id": run.monitoring_run_id,
        "data_hash": run.data_hash,
        "features": json.dumps(list(ANOMALY_FEATURES)),
        "params": json.dumps(params),
        "metrics": json.dumps(metrics),
        "seconds": run.seconds,
        "actor": actor,
    }
    return pd.DataFrame([row])


def run_anomaly(
    db: Database, settings: Settings, *, as_of: date | None = None, actor: str | None = None
) -> AnomalyRun:
    """Score the customer-months as of a date, store the scores and alert on the top fraction."""
    started = time.perf_counter()
    as_of = as_of or settings.data.reference_date
    actor = actor or settings.audit.system_actor
    cfg = settings.ml.anomaly
    scored = _score(db, settings, as_of)  # raises before anything is written
    metrics = score_metrics(scored.samples["score"])
    run_id = _next_run_id(db)
    model_version = f"{ANOMALY_VERSION}/{run_id}"
    alerts = _alert_records(scored, model_version)

    db.insert_df("anomaly_scores", _score_rows(run_id, model_version, scored))
    rules = [RuleRun(RULE_ID, model_version, cfg.model_dump(mode="json"))]
    monitoring_run_id = record_run(
        db, as_of=as_of, source=SOURCE_ANOMALY, rules=rules, alerts=alerts
    )
    samples = scored.samples
    run = AnomalyRun(
        run_id=run_id,
        model_version=model_version,
        as_of=as_of,
        samples=len(samples),
        customers=int(samples["cif"].nunique()),
        months=int(samples["month"].nunique()),
        alerts=scored.alerts,
        threshold=scored.threshold,
        graph_source=scored.graph_source,
        monitoring_run_id=monitoring_run_id,
        data_hash=scored.data_hash,
        seconds=round(time.perf_counter() - started, 3),
    )
    event = AuditEvent(
        module=MODULE,
        entity_type="anomaly_run",
        entity_id=str(run_id),
        decision="ANOMALY_RUN_COMPLETED",
        reason=_run_reason(run, scored, settings),
        version=model_version,
        actor=actor,
        details=asdict(run) | {"as_of": as_of.isoformat(), "metrics": metrics},
    )
    with db.transaction():
        db.insert_df("anomaly_runs", _run_row(run, scored, settings, metrics, actor))
        audit_many(db, [event])
    return run
