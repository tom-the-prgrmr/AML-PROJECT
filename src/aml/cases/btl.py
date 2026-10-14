"""The below-the-line (BTL) sample: customers with no alert, labelled from the ground truth.

The case ranking model of Phase 7c only ever sees customers that raised an alert, so nobody knows
how it ranks the customers under the cut-off or how many suspicious ones the cut-off misses. This
module draws a seeded random sample of golden customers with no alert in the current case run,
labels each one from the synthetic ground truth and computes the 35 case features for it from the
same enrichment blocks as a case.

The labels are measurement and training data and nothing else: no customer of the sample gets an
alert, a case or a disposition. Together with `aml.cases.labels` this is the only place of the
case phase that reads `ground_truth`; the feature code below never does.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from aml.cases.enrich import customer_blocks, read_reference
from aml.cases.enrich_network import choose_source, load_features
from aml.cases.features import DECIMALS, FEATURES, case_features
from aml.cases.items import sql_statement
from aml.cases.labels import has_ground_truth
from aml.cases.model import PrioritizationError
from aml.cases.prio_store import json_column, latest_run, scalar
from aml.cases.runner import CaseError
from aml.cases.values import lower_columns, plain, plain_date
from aml.cases.view import CaseView
from aml.common.audit import AuditEvent, audit_many
from aml.common.config import Settings
from aml.common.db import Database
from aml.memo.features import MEMO_FEATURES, case_memos, count_memos
from aml.memo.store import memo_schema_ready, read_labels

__all__ = [
    "BTL_VERSION",
    "NOT_SUSPICIOUS",
    "SUSPICIOUS",
    "BtlMember",
    "BtlSample",
    "btl_label",
    "btl_population",
    "draw_sample",
    "load_sample",
    "read_btl_features",
    "seeded_positions",
    "wilson_interval",
    "write_btl_features",
]

BTL_VERSION = "btl/v1"
SUSPICIOUS, NOT_SUSPICIOUS = "SUSPICIOUS", "NOT_SUSPICIOUS"
NO_TRUTH = "no ground truth: a below-the-line sample cannot be labelled"
WILSON_Z = 1.959964  # two-sided 95 %

_MODULE = "cases"


def seeded_positions(seed: int, population: int, size: int) -> list[int]:
    """Ascending positions of a seeded random sample without replacement (capped at the size)."""
    take = min(size, population)
    if take <= 0:
        return []
    chosen = np.random.default_rng(seed).choice(population, size=take, replace=False)
    return sorted(int(i) for i in chosen)


def wilson_interval(k: int, n: int) -> tuple[float | None, float | None]:
    """95 % Wilson interval of ``k`` successes in ``n`` trials, rounded to 4; None for n = 0."""
    if n <= 0:
        return None, None
    p, z2 = k / n, WILSON_Z**2
    scale = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / scale
    half = WILSON_Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / scale
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


@dataclass(frozen=True)
class BtlMember:
    golden_customer_id: str
    label: str  # SUSPICIOUS | NOT_SUSPICIOUS
    typologies: tuple[str, ...]  # ascending; () when NOT_SUSPICIOUS
    reason: str


def btl_label(golden_customer_id: str, run_id: int, typologies: Sequence[str]) -> BtlMember:
    """The label of a customer that was not alerted in case run ``run_id``. Pure."""
    names = tuple(sorted(set(typologies)))
    head = f"below-the-line sample: not alerted in case run {run_id}"
    if names:
        reason = f"{head}, but in a suspicious scenario ({', '.join(names)})"
        return BtlMember(golden_customer_id, SUSPICIOUS, names, reason)
    return BtlMember(
        golden_customer_id, NOT_SUSPICIOUS, (), f"{head} and in no suspicious scenario"
    )


@dataclass(frozen=True)
class BtlSample:
    sample_id: int
    run_id: int
    as_of: date
    seed: int
    requested: int  # the sample_size asked for
    population: int
    size: int  # min(requested, population)
    suspicious: int
    not_suspicious: int
    estimated_missed: int  # round(population * suspicious / size); 0 when size = 0
    prevalence_ci95: tuple[float | None, float | None]
    members: tuple[BtlMember, ...]  # ascending golden_customer_id
    reused: bool  # True when the sample of (run_id, seed, requested) already existed


def _read(db: Database, sql: str) -> pd.DataFrame:
    return lower_columns(db.query_df(sql))


def _query(db: Database, name: str, run_id: int | None = None) -> pd.DataFrame:
    sql = sql_statement(db, f"cases/{name}.sql")
    return lower_columns(db.query_df(sql.replace("{run_id}", str(int(run_id or 0)))))


def btl_population(db: Database, run_id: int) -> list[str]:
    """Golden customers with no ``case_alerts`` row in the case run, ascending."""
    return sorted(str(g) for g in _query(db, "btl_population", run_id)["golden_customer_id"])


def _typologies(db: Database, golden_ids: set[str]) -> dict[str, tuple[str, ...]]:
    """Typologies of the suspicious scenarios each of the customers belongs to (ground truth)."""
    df = _query(db, "btl_truth")
    found: dict[str, set[str]] = {}
    for golden_id, typology, suspicious in zip(
        df["golden_customer_id"], df["typology"], df["is_suspicious"], strict=True
    ):
        if str(golden_id) in golden_ids and bool(suspicious):  # BOOLEAN or NUMBER
            found.setdefault(str(golden_id), set()).add(str(typology))
    return {g: tuple(sorted(t)) for g, t in found.items()}


def _run(db: Database) -> tuple[int, date]:
    try:
        return latest_run(db)
    except PrioritizationError as exc:
        raise CaseError(str(exc)) from exc


def _interval(row: Any) -> tuple[float | None, float | None]:
    low, high = plain(row.ci_low), plain(row.ci_high)
    return (None if low is None else float(low), None if high is None else float(high))


def load_sample(db: Database, sample_id: int, *, reused: bool = False) -> BtlSample:
    """A stored sample with its members; raises when the id is unknown."""
    head = _read(db, f"SELECT * FROM btl_samples WHERE sample_id = {int(sample_id)}")
    if head.empty:
        raise PrioritizationError(f"unknown below-the-line sample {sample_id}")
    r = next(head.itertuples())
    rows = _read(
        db,
        "SELECT golden_customer_id, label, typologies, reason FROM btl_members "
        f"WHERE sample_id = {int(sample_id)}",
    )
    members = tuple(
        BtlMember(str(g), str(label), tuple(json_column(t)), str(reason))
        for g, label, t, reason in sorted(
            zip(
                rows["golden_customer_id"], rows["label"], rows["typologies"], rows["reason"],
                strict=True,
            ),
            key=lambda item: str(item[0]),
        )
    )  # fmt: skip
    return BtlSample(
        sample_id=int(r.sample_id),
        run_id=int(r.run_id),
        as_of=plain_date(r.as_of),
        seed=int(r.seed),
        requested=int(r.requested),
        population=int(r.population),
        size=int(r.sample_size),
        suspicious=int(r.suspicious),
        not_suspicious=int(r.not_suspicious),
        estimated_missed=int(r.estimated_missed),
        prevalence_ci95=_interval(r),
        members=members,
        reused=reused,
    )


def _sample_reason(s: BtlSample) -> str:
    low, high = ("-" if v is None else v for v in s.prevalence_ci95)
    return (
        f"sampled {s.size} of {s.population} customer(s) with no alert in case run {s.run_id} "
        f"(seed {s.seed}): {s.suspicious} in a suspicious scenario, estimated "
        f"{s.estimated_missed} missed (95% CI {low}-{high}); measurement only"
    )


def _events(s: BtlSample, settings: Settings, actor: str) -> list[AuditEvent]:
    simulated = settings.cases.prioritization.simulated_actor
    events = [
        AuditEvent(
            module=_MODULE,
            entity_type="customer",
            entity_id=m.golden_customer_id,
            decision="BTL_LABELLED",
            reason=m.reason,
            version=BTL_VERSION,
            actor=simulated,
            details={
                "sample_id": s.sample_id,
                "run_id": s.run_id,
                "label": m.label,
                "typologies": list(m.typologies),
            },
        )
        for m in s.members
    ]
    events.append(
        AuditEvent(
            module=_MODULE,
            entity_type="btl_sample",
            entity_id=str(s.sample_id),
            decision="BTL_SAMPLED",
            reason=_sample_reason(s),
            version=BTL_VERSION,
            actor=actor,
            details={
                "sample_id": s.sample_id,
                "run_id": s.run_id,
                "as_of": s.as_of.isoformat(),
                "seed": s.seed,
                "requested": s.requested,
                "population": s.population,
                "size": s.size,
                "suspicious": s.suspicious,
                "not_suspicious": s.not_suspicious,
                "estimated_missed": s.estimated_missed,
                "prevalence_ci95": list(s.prevalence_ci95),
            },
        )
    )
    return events


def _store(db: Database, s: BtlSample, settings: Settings, actor: str) -> None:
    """The sample, its members and their audit rows, in one transaction."""
    low, high = s.prevalence_ci95
    head = {
        "sample_id": s.sample_id, "run_id": s.run_id, "as_of": s.as_of, "seed": s.seed,
        "requested": s.requested, "population": s.population, "sample_size": s.size,
        "suspicious": s.suspicious, "not_suspicious": s.not_suspicious,
        "estimated_missed": s.estimated_missed, "ci_low": low, "ci_high": high,
        "version": BTL_VERSION, "sampled_ts": datetime.now(UTC).replace(tzinfo=None),
        "actor": actor,
    }  # fmt: skip
    members = pd.DataFrame(
        [
            {
                "sample_id": s.sample_id,
                "golden_customer_id": m.golden_customer_id,
                "label": m.label,
                "typologies": json.dumps(list(m.typologies)),
                "reason": m.reason,
            }
            for m in s.members
        ]
    )
    head_frame = pd.DataFrame([head])
    head_frame["ci_low"] = pd.Series([low], dtype=object)  # None stays NULL, not NaN
    head_frame["ci_high"] = pd.Series([high], dtype=object)
    with db.transaction():
        db.insert_df("btl_samples", head_frame)
        if s.members:
            db.insert_df("btl_members", members)
        audit_many(db, _events(s, settings, actor))


def draw_sample(
    db: Database, settings: Settings, *, size: int | None = None, actor: str | None = None
) -> BtlSample:
    """The below-the-line sample of the newest case run, drawn once per (run, seed, size).

    Raises `CaseError` without a case run and `PrioritizationError` without ground truth, both
    before anything is written. A sample that already exists is returned with ``reused = True``
    and nothing is written.
    """
    requested = settings.cases.prioritization.below_the_line.sample_size if size is None else size
    if requested < 1:
        raise PrioritizationError("below-the-line sample size must be >= 1")
    run_id, as_of = _run(db)
    if not has_ground_truth(db):
        raise PrioritizationError(NO_TRUTH)
    seed = settings.seed
    existing = _read(
        db,
        f"SELECT sample_id FROM btl_samples WHERE run_id = {run_id} AND seed = {seed} "
        f"AND requested = {requested} ORDER BY sample_id",
    )
    if not existing.empty:
        return load_sample(db, int(existing["sample_id"].iloc[0]), reused=True)
    ids = btl_population(db, run_id)
    chosen = [ids[i] for i in seeded_positions(seed, len(ids), requested)]
    truth = _typologies(db, set(chosen))
    members = tuple(btl_label(g, run_id, truth.get(g, ())) for g in chosen)
    suspicious = sum(m.label == SUSPICIOUS for m in members)
    sample = BtlSample(
        sample_id=1 + scalar(db, "SELECT COALESCE(MAX(sample_id), 0) FROM btl_samples"),
        run_id=run_id,
        as_of=as_of,
        seed=seed,
        requested=requested,
        population=len(ids),
        size=len(members),
        suspicious=suspicious,
        not_suspicious=len(members) - suspicious,
        estimated_missed=round(len(ids) * suspicious / len(members)) if members else 0,
        prevalence_ci95=wilson_interval(suspicious, len(members)),
        members=members,
        reused=False,
    )
    _store(db, sample, settings, actor or settings.cases.prioritization.simulated_actor)
    return sample


# ---------------------------------------------------------------- features (no ground truth below)
def _view(sample: BtlSample, golden_id: str, blocks: dict[str, dict[str, Any]]) -> CaseView:
    """A case view with no alert and the enrichment of the customer, to reuse `case_features`."""
    stamp = datetime.combine(sample.as_of, datetime.min.time())
    return CaseView(
        case_id="", run_id=sample.run_id, golden_customer_id=golden_id, status="",
        window_start=stamp, first_alert_ts=stamp, last_alert_ts=stamp, reason="", alerts=(),
        enrichment=blocks, subjects=(), disposition=None, score=None,
    )  # fmt: skip


def _feature_rows(db: Database, settings: Settings, sample: BtlSample) -> list[dict[str, Any]]:
    """Long rows (sample, customer, feature, value) from the enrichment blocks of a case."""
    ref = read_reference(db, settings, sample.run_id, sample.as_of)
    source = choose_source(db, settings.cases.graph_features, sample.as_of)
    network = load_features(db, source)
    end = pd.Timestamp(sample.as_of)
    rows = []
    for member in sample.members:
        golden_id = member.golden_customer_id
        blocks = customer_blocks(
            db, settings, ref, source, network, golden_id,
            end=end, case_id="", window_start=end, shared=[],
        )  # fmt: skip
        for name, value in case_features(_view(sample, golden_id, blocks)).items():
            rows.append(
                {
                    "sample_id": sample.sample_id,
                    "golden_customer_id": golden_id,
                    "feature": name,
                    "value": round(value, DECIMALS),
                }
            )
    return rows


def write_btl_features(db: Database, settings: Settings, sample_id: int) -> int:
    """Store the 35 features of every member of a sample; 0 when they are already stored."""
    sample = load_sample(db, sample_id)
    if scalar(db, f"SELECT COUNT(*) FROM btl_features WHERE sample_id = {int(sample_id)}"):
        return 0
    rows = _feature_rows(db, settings, sample)
    return db.insert_df("btl_features", pd.DataFrame(rows)) if rows else 0


def _memo_columns(db: Database, settings: Settings, sample: BtlSample) -> pd.DataFrame | None:
    """Six memo counts of each member over the feature window; None until every memo has a label."""
    if not memo_schema_ready(db):
        return None
    found = read_labels(db, settings)
    if found.empty:
        return None
    labels = {
        key: (category, method)
        for key, category, method in zip(
            found["memo_key"], found["category"], found["method"], strict=True
        )
    }
    ids = [m.golden_customer_id for m in sample.members]
    pairs = _query(db, "btl_cifs")
    wanted = set(ids)
    cifs: dict[str, list[str]] = {}
    for golden_id, cif in zip(pairs["golden_customer_id"], pairs["cif"], strict=True):
        if str(golden_id) in wanted:
            cifs.setdefault(str(golden_id), []).append(str(cif))
    end = sample.as_of
    start = end - timedelta(days=settings.cases.txn_summary_days - 1)
    rows = {}
    for golden_id in ids:
        counts = count_memos(
            case_memos(db, sorted(cifs.get(golden_id, [])), start, end),
            labels,
            settings.memo.max_chars,
        )
        if counts is None:
            return None  # all or nothing, like the memo features of a case run
        rows[golden_id] = counts
    frame = pd.DataFrame.from_dict(rows, orient="index", columns=list(MEMO_FEATURES))
    return frame.sort_index().rename_axis("golden_customer_id")


def read_btl_features(
    db: Database, settings: Settings, sample_id: int, *, memo: bool = False
) -> pd.DataFrame | None:
    """Stored features of a sample: index ``golden_customer_id`` ascending, columns `FEATURES`.

    With ``memo`` the six memo columns follow; they are computed now and are None until every memo
    in the windows has a label.
    """
    df = _read(
        db,
        "SELECT golden_customer_id, feature, value FROM btl_features "
        f"WHERE sample_id = {int(sample_id)}",
    )
    if df.empty:
        wide = pd.DataFrame(columns=list(FEATURES), dtype=float)
    else:
        wide = df.pivot(index="golden_customer_id", columns="feature", values="value")
        wide = wide.astype(float).reindex(columns=list(FEATURES))
        if wide.isna().any().any():
            raise PrioritizationError(f"btl_features of sample {sample_id} is incomplete")
    wide.columns.name = None
    wide = wide.loc[sorted(wide.index)].rename_axis("golden_customer_id")
    if not memo:
        return wide
    columns = _memo_columns(db, settings, load_sample(db, sample_id))
    return None if columns is None else wide.join(columns)
