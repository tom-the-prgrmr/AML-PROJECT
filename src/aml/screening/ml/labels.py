"""Simulated investigator labels on screening hits, and the labels a model trains on.

This is the only place where the screening model reads the ground truth. It plays the investigator
for a seeded share of the entries so a model has labelled pairs to learn from. A simulated label
is a row of its own table with ``origin = SIMULATED`` and its own audit module: it is never a
review of a person, so nothing that lists reviews can show it. A pair that a person already
reviewed is never labelled again, and with ``use_human_reviews`` that review wins at training.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from aml.common.audit import AuditEvent, audit_many
from aml.common.config import Settings
from aml.common.db import Database
from aml.screening.ml.model import ScreeningMlError
from aml.screening.ml.store import VERSION, count, next_id, require_schema, run_query
from aml.screening.review import latest_reviews

__all__ = ["LabelSimulation", "simulate_labels", "training_labels"]

MODULE = "screening_ml"
SIMULATED, HUMAN = "SIMULATED", "HUMAN"
POSITIVE, NEGATIVE = "TRUE_MATCH", "FALSE_MATCH"
NO_SCREENING = "no screening results: run `aml screen` first"
_PREFIX = "simulated from ground truth:"
Pair = tuple[str, str]


@dataclass(frozen=True)
class LabelSimulation:
    groups: int  # distinct entries among the current hits
    labelled_groups: int
    labelled: int  # labels written by this call
    true_match: int
    false_match: int
    held_out: int  # current pairs without any label after the call
    skipped: int  # pairs of a selected entry that already had a label (simulated or a person's)


def _current(db: Database) -> pd.DataFrame:
    require_schema(db)
    try:
        df = run_query(db, "current_pairs")
    except Exception as exc:  # the table is missing: driver-specific error types
        raise ScreeningMlError(f"{NO_SCREENING} ({exc})") from exc
    if df.empty:
        raise ScreeningMlError(NO_SCREENING)
    return df.sort_values(["entry_id", "cif"]).reset_index(drop=True)


def _selected_entries(entries: list[str], settings: Settings) -> set[str]:
    """The first ``ceil(fraction * n)`` of a seeded permutation of the sorted entry ids."""
    n = len(entries)
    take = math.ceil(round(settings.ml.screening.simulate_fraction * n, 9))  # 0.7 * 10 -> 7
    order = np.random.default_rng(settings.seed).permutation(n)
    return {entries[i] for i in order[:take]}


def _typologies(db: Database) -> dict[Pair, str]:
    df = run_query(db, "truth_typologies")
    return {
        (str(c), str(e)): str(t)
        for c, e, t in zip(df["cif"], df["entry_id"], df["typology"], strict=True)
    }


def simulate_labels(db: Database, settings: Settings) -> LabelSimulation:
    """Label, from the ground truth, every unlabelled hit of a seeded share of the entries.

    Raises `ScreeningMlError` before writing anything when there is no screening result or no
    ground truth. The pairs of the other entries stay unlabelled: they are the held-out set.
    """
    cfg = settings.ml.screening
    current = _current(db)
    if count(db, "ground_truth") == 0:
        raise ScreeningMlError("no ground truth: nothing to simulate labels from")
    entries = sorted(set(current["entry_id"]))
    chosen = _selected_entries(entries, settings)
    truth = _typologies(db)
    simulated = set(map(tuple, run_query(db, "labelled_pairs")[["cif", "entry_id"]].to_numpy()))
    reviewed = set(latest_reviews(db))
    first_id = next_id(db, "screening_ml_labels", "label_id")
    now = datetime.now(UTC).replace(tzinfo=None)
    rows: list[dict[str, object]] = []
    events: list[AuditEvent] = []
    skipped = held_out = 0
    for r in current.itertuples():
        pair = (str(r.cif), str(r.entry_id))
        has_label = pair in simulated or pair in reviewed
        if r.entry_id not in chosen:
            held_out += not has_label
        elif has_label:
            skipped += 1
        else:
            label_id = first_id + len(rows)
            label = POSITIVE if pair in truth else NEGATIVE
            reason = (
                f"{_PREFIX} planted {truth[pair]} true match"
                if pair in truth
                else f"{_PREFIX} not a planted true match"
            )
            rows.append(
                {
                    "label_id": label_id,
                    "cif": pair[0],
                    "entry_id": pair[1],
                    "label": label,
                    "origin": SIMULATED,
                    "actor": cfg.simulated_actor,
                    "reason": reason,
                    "labelled_ts": now,
                }
            )
            events.append(
                AuditEvent(
                    module=MODULE,
                    entity_type="screening_label",
                    entity_id=f"{pair[0]}:{pair[1]}",
                    decision="SIMULATED_LABEL",
                    reason=reason,
                    version=VERSION,
                    actor=cfg.simulated_actor,
                    details={
                        "label_id": label_id,
                        "label": label,
                        "origin": SIMULATED,
                        "result_run_id": int(r.result_run_id),
                    },
                )
            )
    true_match = sum(row["label"] == POSITIVE for row in rows)
    sim = LabelSimulation(
        groups=len(entries),
        labelled_groups=len(chosen),
        labelled=len(rows),
        true_match=true_match,
        false_match=len(rows) - true_match,
        held_out=held_out,
        skipped=skipped,
    )
    events.append(
        AuditEvent(
            module=MODULE,
            entity_type="screening_label_run",
            entity_id=str(int(current["result_run_id"].max())),
            decision="LABELS_SIMULATED",
            reason=(
                f"simulated {sim.labelled} label(s) from ground truth on {sim.labelled_groups} of "
                f"{sim.groups} watchlist entries: {sim.true_match} TRUE_MATCH, "
                f"{sim.false_match} FALSE_MATCH; {sim.skipped} already labelled, "
                f"{sim.held_out} left unlabelled"
            ),
            version=VERSION,
            actor=cfg.simulated_actor,
            details=asdict(sim),
        )
    )
    with db.transaction():
        if rows:
            db.insert_df("screening_ml_labels", pd.DataFrame(rows))
        audit_many(db, events)
    return sim


def training_labels(db: Database, settings: Settings) -> pd.DataFrame:
    """Labels of the current pairs that have one: index ``(cif, entry_id)``, ``label``, ``origin``.

    A person's newest review (when ``use_human_reviews``) beats the newest simulated label.
    """
    simulated = run_query(db, "latest_labels")
    found: dict[Pair, tuple[int, str]] = {
        (str(r.cif), str(r.entry_id)): (int(r.label == POSITIVE), SIMULATED)
        for r in simulated.itertuples()
    }
    if settings.ml.screening.use_human_reviews:
        current = {tuple(p) for p in run_query(db, "current_pairs")[["cif", "entry_id"]].to_numpy()}
        for pair, review in latest_reviews(db).items():
            if pair in current:
                found[pair] = (int(review.decision == POSITIVE), HUMAN)
    pairs = sorted(found)
    index = pd.MultiIndex.from_arrays(
        [[p[0] for p in pairs], [p[1] for p in pairs]], names=["cif", "entry_id"]
    )
    values = [found[p] for p in pairs]
    return pd.DataFrame(
        {"label": [v[0] for v in values], "origin": [v[1] for v in values]}, index=index
    )
