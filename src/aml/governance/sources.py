"""One adapter per model card: read what a model stored and return `CardFacts` (or why not).

Each adapter only reads the model's own tables and the audit trail. The two models of the sibling
specs are reached through `importlib`, so a missing module makes the card `Skipped` instead of
breaking the command; their facts are read here from what they stored (the anomaly module gives
a dict that is wrapped, the screening module has no card function and its tables are read
directly).
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator, Mapping
from typing import Any

import pandas as pd

from aml.cases.model import PrioritizationError
from aml.cases.prio_store import json_column, read_model
from aml.cases.values import lower_columns, plain_date
from aml.common.config import Settings
from aml.common.db import Database
from aml.governance.audit_check import json_text, table_exists
from aml.governance.cards import AuditCoverage, CardFacts, Skipped, not_implemented
from aml.memo.normalize import MEMO_VERSION
from aml.memo.store import by_category, by_method, memo_schema_ready, read_labels

__all__ = [
    "anomaly_facts",
    "memo_classifier_facts",
    "prioritization_facts",
    "screening_match_facts",
]

NO_STORED_MODEL = "no stored model: run `aml cases train` first"
NO_MEMO_RUN = "no memo run: run `aml memo classify` first"
NO_ANOMALY_RUN = "no anomaly run: run `aml anomaly run` first"
NO_SCREENING_MODEL = "no model: run `aml screen-ml train` first"
NOT_SCORED = "not scored yet"
NOT_MEASURED = "not measured: run `aml cases btl`"
NOT_EVALUATED = "not evaluated: run `aml memo eval`"

_SCALARS = (
    "n", "n_suspicious", "n_false_positive", "prevalence", "roc_auc", "pr_auc", "population",
    "estimated_missed", "excluded_trained",
)  # fmt: skip
_Rows = list[tuple[str, str, str]]


# ---------------------------------------------------------------- small readers
def _fmt(value: Any) -> str:
    return "-" if value is None else str(value)


def _iso(value: Any) -> str:
    """A stored UTC timestamp as ``2026-10-14T09:30:00Z`` (the same text on both backends)."""
    return pd.Timestamp(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _one(db: Database, sql: str) -> pd.Series | None:
    df = lower_columns(db.query_df(sql))
    return None if df.empty else df.iloc[0]


def _details(db: Database, module: str, decision: str, version: str, extra: str = "") -> Any:
    """``details`` of the newest audit row of a decision for a version; None when there is none."""
    column = "JSON_SERIALIZE(details RETURNING CLOB)" if db.backend == "oracle" else "details"
    where = f"module = '{module}' AND decision = '{decision}' AND version = '{version}'{extra}"
    row = _one(
        db,
        f"SELECT {column} AS details FROM audit_log "
        f"WHERE audit_id = (SELECT MAX(audit_id) FROM audit_log WHERE {where})",
    )
    return None if row is None or row["details"] is None else json_column(row["details"])


def _coverage(
    db: Database,
    module: str,
    decision: str,
    version: str,
    *,
    where: str = "",
    ok_when: str = "",
    expected: str = "",
) -> AuditCoverage:
    """Audit rows of a decision (narrowed by ``where``) and how many of them carry a version.

    A row counts as carrying the version when its version is ``expected`` (the card's version by
    default) and, if given, ``ok_when`` also holds.
    """
    wanted = expected or version
    row = _one(
        db,
        f"SELECT COUNT(*) AS n, "
        f"COALESCE(SUM(CASE WHEN version = '{wanted}'{ok_when} THEN 1 ELSE 0 END), 0) AS ok "
        f"FROM audit_log WHERE module = '{module}' AND decision = '{decision}'{where}",
    )
    assert row is not None
    return AuditCoverage(module, decision, int(row["n"]), int(row["ok"]), expected or None)


def _flat(
    value: Any, name: str = "", skip: frozenset[str] = frozenset()
) -> Iterator[tuple[str, str]]:
    """``(dotted name, text)`` of every scalar in nested dicts and lists.

    A list item is named by its ``baseline`` when it has one, else by its position.
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) not in skip:
                yield from _flat(item, f"{name}.{key}" if name else str(key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            named = isinstance(item, Mapping) and "baseline" in item
            body = {k: v for k, v in item.items() if k != "baseline"} if named else item
            yield from _flat(body, f"{name}[{item['baseline'] if named else i}]")
    else:
        yield name, _fmt(value)


def _rows(population: str, metrics: Mapping[str, Any], skip: frozenset[str] = frozenset()) -> _Rows:
    return [(population, name, text) for name, text in _flat(metrics, skip=skip)]


def _ranking_rows(population: str, m: Mapping[str, Any]) -> _Rows:
    """The scalar ranking metrics of one population, then precision / recall at each fraction."""
    rows = [(population, key, _fmt(m[key])) for key in _SCALARS if key in m]
    if "prevalence_ci95" in m:
        low, high = (_fmt(v) for v in m["prevalence_ci95"])
        rows.append((population, "prevalence_ci95", f"{low}-{high}"))
    for key in ("precision_at", "recall_at"):
        for fraction, value in sorted((m.get(key) or {}).items(), key=lambda kv: float(kv[0])):
            rows.append((population, f"{key.removesuffix('_at')}@{fraction}", _fmt(value)))
    return rows


# ---------------------------------------------------------------- case prioritization
_PRIORITIZATION_LIMITS = (
    "Labels are simulated from synthetic ground truth, not given by investigators.",
    "Scores are rankings, not calibrated probabilities.",
    "The active model is the newest one: there is no approval step.",
)
_BTL_LIMITS = (
    "Every below-the-line customer has no alert and every case has at least one, so the pooled "
    "cross-validation metrics of a +btl model are inflated: only the per-population rows mean "
    "anything.",
    "The below-the-line sample is small and its labels are exact: read its metrics with its size "
    "and the confidence interval.",
)


_ANOMALY_ZEROS = (
    "The below-the-line measurement zero-fills the anomaly features this model uses, so its "
    "metrics understate what the model sees on a case.",
)


def _btl_rows(db: Database, model_id: int) -> _Rows:
    if not table_exists(db, "btl_evaluations"):
        return [("below-the-line", "status", NOT_MEASURED)]
    row = _one(
        db,
        "SELECT metrics FROM btl_evaluations WHERE eval_id = "
        f"(SELECT MAX(eval_id) FROM btl_evaluations WHERE model_id = {model_id})",
    )
    if row is None:
        return [("below-the-line", "status", NOT_MEASURED)]
    return _ranking_rows("below-the-line", json_column(row["metrics"]))


def prioritization_facts(db: Database, settings: Settings) -> CardFacts | Skipped:
    """The card of the active case-ranking model (`case_model_active`)."""
    try:
        model_id, version, model = read_model(db, None)
    except PrioritizationError:
        return Skipped("prioritization", NO_STORED_MODEL)
    row = _one(
        db,
        "SELECT trained_ts, seed, as_of, cases, suspicious, false_positive FROM case_models "
        f"WHERE model_id = {model_id}",
    )
    assert row is not None
    population = model.params.get("population") or {}
    variant = bool(population)
    metrics = _ranking_rows("cross-validation", model.metrics)
    for name, part in (model.metrics.get("by_population") or {}).items():
        metrics += _ranking_rows(f"cross-validation ({name})", part)
    scored = _details(db, "cases", "SCORING_RUN_COMPLETED", version)
    if scored is None:
        metrics.append(("holdout", "status", NOT_SCORED))
    elif not scored.get("holdout"):
        metrics.append(("holdout", "status", "not available: no ground truth"))
    else:
        metrics += _ranking_rows("holdout", scored["holdout"])
    metrics += _btl_rows(db, model_id)
    data = [
        f"{int(row['cases'])} training rows: {int(row['suspicious'])} labelled SUSPICIOUS, "
        f"{int(row['false_positive'])} labelled FALSE_POSITIVE",
        f"Case run as of {plain_date(row['as_of']).isoformat()}",
        "Labels: the latest disposition of each decided case, from the feature snapshot it was "
        "decided on",
    ]
    if variant:
        a, b = population.get("alerted", [0, 0]), population.get("below_the_line", [0, 0])
        data.append(
            f"Alerted cases: {a[0]} SUSPICIOUS, {a[1]} FALSE_POSITIVE; below-the-line sample "
            f"{population.get('btl_sample_id')}: {b[0]} SUSPICIOUS, {b[1]} NOT_SUSPICIOUS"
        )
    if "memo" in model.params:
        data.append(f"Memo features from the labels of {model.params['memo'].get('model')}")
    measured = _details(db, "cases", "BTL_EVALUATED", version)
    zero_filled = bool(measured) and measured.get("anomaly_features") == "zeros"
    return CardFacts(
        name="prioritization",
        title="Case prioritization" + (" (with below-the-line sample)" if variant else ""),
        version=version,
        kind=model.kind,
        trained=_iso(row["trained_ts"]),
        seed=int(row["seed"]),
        data_hash=model.data_hash,
        feature_version=model.feature_version,
        features=model.features,
        source=f"case_models.model_id={model_id}",
        intended_use=(
            "Rank the open case queue so that the cases most likely to be suspicious come first."
        ),
        oversight="It only orders the queue; a person records every disposition.",
        data=tuple(data),
        metrics=tuple(metrics),
        limitations=(
            f"Cross-validated prevalence is {_fmt(model.metrics.get('prevalence'))}.",
            *_PRIORITIZATION_LIMITS,
            *(_BTL_LIMITS if variant else ()),
            *(_ANOMALY_ZEROS if zero_filled else ()),
        ),
        audit=tuple(
            _coverage(db, "cases", decision, version)
            for decision in ("PRIORITIZED", "MODEL_TRAINED", "BTL_EVALUATED")
        ),
    )


# ---------------------------------------------------------------- memo classifier
def _memo_metrics(ev: Mapping[str, Any] | None) -> _Rows:
    if ev is None:
        return [("gold set", "status", NOT_EVALUATED)]
    rows = [("gold set", key, _fmt(ev.get(key))) for key in ("n", "correct", "accuracy")]
    for source, part in (ev.get("by_source") or {}).items():
        rows.append(("gold set", f"accuracy ({source})", _fmt(part.get("accuracy"))))
    for category, part in (ev.get("by_category") or {}).items():
        if part.get("n"):
            rows.append(("gold set", f"recall ({category})", _fmt(part.get("recall"))))
    return rows


def memo_classifier_facts(db: Database, settings: Settings) -> CardFacts | Skipped:
    """The card of the memo classifier: the prompt version and the LLM named in the settings."""
    model = settings.ollama.llm_model
    version = f"{MEMO_VERSION} + {model}"
    run = (
        _one(
            db,
            "SELECT * FROM memo_runs WHERE run_id = (SELECT MAX(run_id) FROM memo_runs "
            f"WHERE memo_version = '{MEMO_VERSION}' AND llm_model = '{model}')",
        )
        if memo_schema_ready(db)
        else None
    )
    if run is None:
        return Skipped("memo_classifier", NO_MEMO_RUN)
    labels = read_labels(db, settings)
    methods = ", ".join(f"{k}={v}" for k, v in by_method(labels).items())
    categories = ", ".join(f"{k}={v}" for k, v in by_category(labels).items())
    own = f" AND {json_text(db, 'model')} = '{model}'"
    evaluated = _details(db, "memo", "MEMO_EVAL_COMPLETED", MEMO_VERSION, own)
    return CardFacts(
        name="memo_classifier",
        title="Memo classifier",
        version=version,
        kind="rules + local LLM",
        trained=_iso(run["run_ts"]),
        seed=None,
        data_hash=None,
        feature_version=None,
        features=(),
        source=f"memo_runs.run_id={int(run['run_id'])}",
        intended_use=(
            "Label the free-text memo of a transaction with one of a closed set of categories, "
            "to give the case ranking model six memo counts."
        ),
        oversight=(
            "A label is a ranking feature only; a person can relabel any memo and the person's "
            "label wins."
        ),
        data=(
            f"{int(run['memo_keys'])} normalised memo keys from {int(run['with_memo'])} "
            "transactions with a memo",
            f"Labels in force by method: {methods}",
            f"Labels in force by category: {categories}",
        ),
        metrics=tuple(_memo_metrics(evaluated)),
        limitations=(
            "The gold set is synthetic and labelled by the project team, not by investigators.",
            "The digest of the Ollama model is not stored: a different model under the same name "
            "would not be noticed.",
            "Memo text is untrusted: a rule layer catches known instruction-like text before any "
            "model call and the model only ever returns one of the fixed category names.",
        ),
        audit=(
            _coverage(db, "memo", "MEMO_CLASSIFIED", MEMO_VERSION, ok_when=own),
            _coverage(db, "memo", "MEMO_EVAL_COMPLETED", MEMO_VERSION, ok_when=own),
        ),
    )


# ---------------------------------------------------------------- anomaly
def anomaly_facts(db: Database, settings: Settings) -> CardFacts | Skipped:
    """The card of the isolation forest: the dict of `aml.ml.anomaly.card.card_facts` wrapped."""
    module = "aml.ml.anomaly.card"
    try:
        card = importlib.import_module(module)
    except ImportError:
        return Skipped("anomaly", not_implemented(module))
    error = importlib.import_module("aml.ml.anomaly.runner").AnomalyError
    try:
        d = card.card_facts(db, settings)
    except error:
        return Skipped("anomaly", NO_ANOMALY_RUN)
    model, data, alerts = d["model"], d["data"], d["alerts"]
    version = str(model["version"])
    metrics = _rows("score distribution", d["metrics"])
    if d.get("evaluation"):
        skip = frozenset({"run_id", "model_version", "as_of", "coverage"})
        metrics += _rows("ground-truth evaluation", d["evaluation"], skip)
    return CardFacts(
        name="anomaly",
        title="Anomaly detection (isolation forest per customer-month)",
        version=version,
        kind=str(model["kind"]),
        trained=_iso(model["trained_ts"]),
        seed=int(model["seed"]),
        data_hash=str(data["data_hash"]),
        feature_version=str(model["feature_version"]),
        features=tuple(f["name"] for f in d["features"]),
        source=f"anomaly_runs.run_id={version.rsplit('/', 1)[-1]}",
        intended_use=(
            f"Score how unusual each customer-month is among its peers: {d['use']['purpose']}."
        ),
        oversight="Its alerts are signals for a person to review; it closes and clears nothing.",
        data=(
            f"{data['samples']} customer-months of {data['customers']} customers "
            f"({data['first_month']} to {data['last_month']}); synthetic data",
            f"Graph features from: {data['graph_source']}",
            f"Alerts: {alerts['count']} (top fraction {alerts['top_fraction']}, "
            f"threshold {alerts['threshold']})",
        ),
        metrics=tuple(metrics),
        limitations=tuple(d["limitations"]),
        audit=(
            _coverage(
                db,
                "monitoring",
                "ALERT",
                version,
                expected=f"ML_ANOMALY/{version}",
                where=f" AND {json_text(db, 'rule_id')} = 'ML_ANOMALY'",
            ),
            _coverage(db, "ml_anomaly", "ANOMALY_RUN_COMPLETED", version),
        ),
    )


# ---------------------------------------------------------------- screening match model
def _training_origins(db: Database, model_id: int) -> str:
    df = lower_columns(
        db.query_df(
            "SELECT origin, label, COUNT(*) AS n FROM screening_ml_training "
            f"WHERE model_id = {model_id} GROUP BY origin, label"
        )
    )
    counts = {
        (str(o), int(x)): int(n) for o, x, n in zip(df["origin"], df["label"], df["n"], strict=True)
    }
    parts = [
        f"{origin}: {counts.get((origin, 1), 0)} TRUE_MATCH, "
        f"{counts.get((origin, 0), 0)} FALSE_MATCH"
        for origin in sorted({origin for origin, _ in counts})
    ]
    return "; ".join(parts) if parts else "none stored"


def screening_match_facts(db: Database, settings: Settings) -> CardFacts | Skipped:
    """The card of the learned screening-hit model, read from the `screening_ml_*` tables."""
    module = "aml.screening.ml.pipeline"
    try:
        importlib.import_module(module)
    except ImportError:
        return Skipped("screening_match", not_implemented(module))
    row = (
        _one(db, "SELECT * FROM screening_ml_model_active")
        if table_exists(db, "screening_ml_models")
        else None
    )
    if row is None:
        return Skipped("screening_match", NO_SCREENING_MODEL)
    model_id, version = int(row["model_id"]), str(row["version"])
    metrics = _rows("cross-validation", json_column(row["metrics"]))
    held = _details(db, "screening_ml", "ML_SCORING_COMPLETED", version)
    if held is None:
        metrics.append(("held-out", "status", "not scored yet: run `aml screen-ml score`"))
    elif not held.get("holdout"):
        metrics.append(("held-out", "status", "not available: every hit has a training label"))
    else:
        metrics += _rows("held-out", held["holdout"])
    return CardFacts(
        name="screening_match",
        title="Screening match model",
        version=version,
        kind=str(row["kind"]),
        trained=_iso(row["trained_ts"]),
        seed=int(row["seed"]),
        data_hash=str(row["data_hash"]),
        feature_version=str(row["feature_version"]),
        features=tuple(json_column(row["features"])),
        source=f"screening_ml_models.model_id={model_id}",
        intended_use="Rank the current screening hits by how likely each is a true match.",
        oversight=(
            "It ranks hits next to the Tier 2 decision, which it never changes; a person "
            "reviews every hit."
        ),
        data=(
            f"{int(row['pairs'])} labelled pairs: {int(row['true_match'])} TRUE_MATCH, "
            f"{int(row['false_match'])} FALSE_MATCH "
            f"({int(row['human_labels'])} from human reviews)",
            f"Training pairs by origin: {_training_origins(db, model_id)}",
            "Labels are simulated from synthetic ground truth unless a person reviewed the hit",
        ),
        metrics=tuple(metrics),
        limitations=(
            "Labels are simulated from synthetic ground truth, not given by investigators.",
            "Scores are rankings, not calibrated probabilities.",
            "The comparison with the fixed thresholds is a measurement on hits without a "
            "training label; the model flags nothing.",
        ),
        audit=tuple(
            _coverage(db, "screening_ml", decision, version)
            for decision in ("MODEL_TRAINED", "ML_SCORED", "ML_SCORING_COMPLETED")
        ),
    )
