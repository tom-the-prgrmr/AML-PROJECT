"""Turn Splink output into stored rows: decisions, golden ids, parameter table, audit events."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd

from aml.common.audit import AuditEvent
from aml.common.config import EntityResolutionConfig, Settings
from aml.common.db import Database
from aml.entity_resolution.model import COMPARISONS, Scored

if TYPE_CHECKING:
    from aml.entity_resolution.runner import ErRun

ER_VERSION = "er/v1"
MATCH, REVIEW = "MATCH", "REVIEW"
MW_COLUMNS = [f"mw_{name}" for name in COMPARISONS]
PAIR_COLUMNS = [
    "run_id", "cif_l", "cif_r", "match_weight", "match_probability", "mw_prior",
    *MW_COLUMNS, "decision", "reason",
]  # fmt: skip
RUN_COLUMNS = [
    "run_id", "run_ts", "as_of", "customers_resolved", "blocked_pairs", "match_pairs",
    "review_pairs", "clusters", "merged_clusters", "merged_cifs", "match_threshold",
    "review_threshold", "prior_probability", "version", "splink_version", "config_hash",
]  # fmt: skip


def config_hash(settings: Settings) -> str:
    cfg = settings.entity_resolution.model_dump(mode="json")
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def scalar(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def next_run_id(db: Database) -> int:
    # er_golden counts too: a run that failed before its er_runs row must not reuse its id.
    return 1 + max(
        scalar(db, "SELECT COALESCE(MAX(run_id), 0) FROM er_runs"),
        scalar(db, "SELECT COALESCE(MAX(run_id), 0) FROM er_golden"),
    )


def _weight(value: float) -> float:
    return round(float(value), 4) + 0.0  # + 0.0 turns -0.0 into 0.0


def reason_for(row: pd.Series, decision: str, cfg: EntityResolutionConfig) -> str:
    """Human-readable explanation from the unrounded numbers (identical on every backend)."""
    op = ">=" if decision == MATCH else "<"
    parts = ", ".join(f"{name} {_weight(row[f'mw_{name}']):+.2f}" for name in COMPARISONS)
    return (
        f"match probability {float(row['match_probability']):.4f} {op} {cfg.match_threshold} "
        f"(weight {_weight(row['match_weight']):.2f}: "
        f"prior {_weight(row['mw_prior']):+.2f}, {parts})"
    )


def decide_pairs(scored: Scored, cfg: EntityResolutionConfig) -> pd.DataFrame:
    """Keep MATCH and REVIEW pairs; anything lower is only counted by the caller."""
    rows = []
    for _, row in scored.pairs.iterrows():
        p = float(row["match_probability"])
        if p >= cfg.match_threshold:
            decision = MATCH
        elif p >= cfg.review_threshold:
            decision = REVIEW
        else:
            continue
        rows.append(
            {**row.to_dict(), "decision": decision, "reason": reason_for(row, decision, cfg)}
        )
    return pd.DataFrame(rows, columns=[*scored.pairs.columns, "decision", "reason"])


def golden_ids(cifs: list[str], scored: Scored) -> pd.DataFrame:
    """cif, golden_customer_id ('G-' + smallest CIF of the cluster), cluster_size."""
    cluster_of = dict(zip(scored.clusters["cif"], scored.clusters["cluster_id"], strict=True))
    members: dict[object, list[str]] = {}
    for cif in cifs:
        members.setdefault(cluster_of.get(cif, cif), []).append(cif)
    rows = [
        {"cif": cif, "golden_customer_id": "G-" + min(group), "cluster_size": len(group)}
        for group in members.values()
        for cif in group
    ]
    return pd.DataFrame(rows).sort_values("cif").reset_index(drop=True)


def pair_rows(run_id: int, decided: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "run_id": run_id,
            "cif_l": r.cif_l,
            "cif_r": r.cif_r,
            "match_weight": _weight(r.match_weight),
            "match_probability": round(float(r.match_probability), 6),
            "mw_prior": _weight(r.mw_prior),
            **{c: _weight(getattr(r, c)) for c in MW_COLUMNS},
            "decision": r.decision,
            "reason": r.reason,
        }
        for r in decided.itertuples()
    ]
    return pd.DataFrame(rows, columns=PAIR_COLUMNS)


def golden_rows(run_id: int, golden: pd.DataFrame) -> pd.DataFrame:
    out = golden.copy()
    out.insert(0, "run_id", run_id)
    out["cluster_size"] = out["cluster_size"].astype(int)
    return out


def _number(value: object) -> float | None:
    return None if value is None or pd.isna(value) else float(value)  # type: ignore[arg-type]


def model_rows(run_id: int, scored: Scored) -> pd.DataFrame:
    """The m/u/weight table that produced the scores; null levels carry no numbers."""
    rows = [
        {
            "run_id": run_id,
            "comparison": r.comparison,
            "level_no": int(r.level_no),
            "label": str(r.label)[:100],
            "is_null_level": int(bool(r.is_null_level)),
            "m_probability": _number(r.m),
            "u_probability": _number(r.u),
            "match_weight": _number(r.weight),
        }
        for r in scored.levels.itertuples()
    ]
    frame = pd.DataFrame(rows)
    for column in ("m_probability", "u_probability", "match_weight"):
        frame[column] = frame[column].astype(object).where(frame[column].notna(), None)
    return frame


def insert_run_row(
    db: Database, run: ErRun, settings: Settings, *, prior: float, splink_version: str
) -> None:
    cfg = settings.entity_resolution
    row = {
        **{c: getattr(run, c) for c in RUN_COLUMNS if hasattr(run, c)},
        "run_ts": datetime.now(UTC).replace(tzinfo=None),
        "match_threshold": cfg.match_threshold,
        "review_threshold": cfg.review_threshold,
        "prior_probability": prior,
        "version": ER_VERSION,
        "splink_version": splink_version,
        "config_hash": config_hash(settings),
    }
    db.insert_df("er_runs", pd.DataFrame([row], columns=RUN_COLUMNS))


def merge_events(run_id: int, golden: pd.DataFrame, decided: pd.DataFrame) -> list[AuditEvent]:
    """One MERGED event per multi-CIF cluster, quoting its weakest MATCH link."""
    gid = dict(zip(golden["cif"], golden["golden_customer_id"], strict=True))
    links: dict[str, list[tuple[float, str, str]]] = {}
    for r in decided[decided["decision"] == MATCH].itertuples():
        links.setdefault(gid[r.cif_l], []).append((_weight(r.match_weight), r.cif_l, r.cif_r))
    events = []
    for golden_id, group in golden[golden["cluster_size"] > 1].groupby("golden_customer_id"):
        cifs = sorted(group["cif"])
        cluster_links = sorted(links[str(golden_id)])
        weight, left, right = cluster_links[0]
        events.append(
            AuditEvent(
                module="entity_resolution",
                entity_type="golden_customer",
                entity_id=str(golden_id),
                decision="MERGED",
                reason=(
                    f"linked {len(cifs)} CIFs ({', '.join(cifs)}) by {len(cluster_links)} MATCH "
                    f"pair(s); weakest link {left}-{right} weight {weight:.2f}"
                ),
                version=ER_VERSION,
                details={
                    "run_id": run_id,
                    "cifs": cifs,
                    "pairs": len(cluster_links),
                    "min_match_weight": round(weight, 2),
                },
            )
        )
    return events


def review_events(run_id: int, decided: pd.DataFrame) -> list[AuditEvent]:
    return [
        AuditEvent(
            module="entity_resolution",
            entity_type="er_pair",
            entity_id=f"{r.cif_l}:{r.cif_r}",
            decision=REVIEW,
            reason=r.reason,
            version=ER_VERSION,
            details={
                "run_id": run_id,
                "match_weight": _weight(r.match_weight),
                "match_probability": round(float(r.match_probability), 6),
            },
        )
        for r in decided[decided["decision"] == REVIEW].itertuples()
    ]


def run_event(run: ErRun) -> AuditEvent:
    return AuditEvent(
        module="entity_resolution",
        entity_type="er_run",
        entity_id=str(run.run_id),
        decision="ER_RUN_COMPLETED",
        reason=(
            f"Resolved {run.customers_resolved} customers as of {run.as_of.isoformat()}: "
            f"{run.match_pairs} MATCH and {run.review_pairs} REVIEW pairs of {run.blocked_pairs} "
            f"scored; {run.merged_clusters} merged clusters among {run.clusters}."
        ),
        version=ER_VERSION,
        details={
            "as_of": run.as_of.isoformat(),
            "customers_resolved": run.customers_resolved,
            "blocked_pairs": run.blocked_pairs,
            "match_pairs": run.match_pairs,
            "review_pairs": run.review_pairs,
            "clusters": run.clusters,
            "merged_clusters": run.merged_clusters,
            "merged_cifs": run.merged_cifs,
        },
    )
