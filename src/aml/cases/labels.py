"""Labels from the synthetic ground truth, and simulated dispositions built on them.

This is the only place where the case phase reads `ground_truth`. It plays the investigator for a
share of the case groups so a model has labelled cases to learn from: the decisions it records are
marked ``origin = SIMULATED`` with their own actor, and a decision that already exists (above all
one made by a person) is never overwritten. The remaining cases stay OPEN: the queue to rank.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date

import numpy as np
import pandas as pd

from aml.cases.dispositions import FALSE_POSITIVE, SIMULATED, SUSPICIOUS, record_disposition
from aml.cases.items import sql_statement
from aml.cases.model import PrioritizationError
from aml.cases.runner import CASES_VERSION, CaseError
from aml.cases.values import lower_columns, plain_date
from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database

__all__ = [
    "Simulation",
    "TruthLabel",
    "case_groups",
    "has_ground_truth",
    "simulate_dispositions",
    "truth_labels",
]

_NO_RUN = "no case run yet: run `aml cases build` first"
_PREFIX = "simulated from ground truth:"


@dataclass(frozen=True)
class TruthLabel:
    case_id: str
    disposition: str  # SUSPICIOUS | FALSE_POSITIVE
    true_alerts: int
    alerts: int
    typologies: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Simulation:
    run_id: int
    groups: int
    labelled_groups: int
    labelled: int  # dispositions written by this call
    suspicious: int
    false_positive: int
    held_out: int  # cases without a disposition that were not selected
    skipped: int  # selected cases that already had a disposition


def _latest_run(db: Database) -> tuple[int, date]:
    df = lower_columns(db.query_df("SELECT run_id, as_of FROM case_runs ORDER BY run_id DESC"))
    if df.empty:
        raise CaseError(_NO_RUN)
    return int(df["run_id"].iloc[0]), plain_date(df["as_of"].iloc[0])


def _active_items(db: Database, run_id: int) -> pd.DataFrame:
    return lower_columns(
        db.query_df(
            "SELECT case_id, item_key, source, cif, entry_id FROM case_alerts "
            f"WHERE run_id = {run_id} AND status = 'ACTIVE' AND case_id IS NOT NULL"
        )
    )


def case_groups(db: Database, run_id: int) -> dict[str, str]:
    """``case_id -> group_id``: cases that share an ACTIVE item_key form one group.

    The group id is the smallest case id of the group. A group is labelled whole or not at all,
    because the cases of one ring share alerts and would otherwise leak into each other.
    """
    cases = lower_columns(db.query_df(f"SELECT case_id FROM cases WHERE run_id = {run_id}"))
    parent = {str(c): str(c) for c in cases["case_id"]}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    items = _active_items(db, run_id)
    for case_ids in items.groupby("item_key")["case_id"].agg(lambda s: sorted(set(s))):
        for other in case_ids[1:]:
            a, b = find(case_ids[0]), find(other)
            parent[max(a, b)] = min(a, b)
    return {case_id: find(case_id) for case_id in sorted(parent)}


def _true_pairs(db: Database) -> dict[tuple[str, str], str]:
    """(cif, entry_id) -> typology of the planted sanctions / PEP true hits."""
    df = db.query_df(
        "SELECT c.entity_id AS cif, w.entity_id AS entry_id, c.typology "
        "FROM ground_truth c JOIN ground_truth w ON c.scenario_id = w.scenario_id "
        "WHERE c.entity_type = 'customer' AND w.entity_type = 'watchlist_entry' "
        "AND c.typology IN ('sanctions_hit', 'pep_hit') "
        "AND w.typology IN ('sanctions_hit', 'pep_hit')"
    )
    return {
        (str(c), str(e)): str(t)
        for c, e, t in zip(df["cif"], df["entry_id"], df["typology"], strict=True)
    }


def _true_items(db: Database, run_id: int) -> dict[tuple[str, str], set[str]]:
    """(case_id, item_key) -> typologies of the suspicious scenarios its accounts belong to."""
    sql = sql_statement(db, "cases/truth_accounts.sql").replace("{run_id}", str(int(run_id)))
    df = lower_columns(db.query_df(sql))
    found: dict[tuple[str, str], set[str]] = {}
    for case_id, item_key, typology, suspicious in zip(
        df["case_id"], df["item_key"], df["typology"], df["is_suspicious"], strict=True
    ):
        if bool(suspicious):  # BOOLEAN on DuckDB, NUMBER on Oracle
            found.setdefault((str(case_id), str(item_key)), set()).add(str(typology))
    return found


def _label(case_id: str, true_alerts: int, alerts: int, typologies: set[str]) -> TruthLabel:
    names = tuple(sorted(typologies))
    if true_alerts:
        reason = (
            f"{_PREFIX} {true_alerts} of {alerts} alert(s) match a suspicious scenario "
            f"({', '.join(names)})"
        )
    else:
        reason = f"{_PREFIX} none of the {alerts} alert(s) matches a suspicious scenario"
    return TruthLabel(
        case_id, SUSPICIOUS if true_alerts else FALSE_POSITIVE, true_alerts, alerts, names, reason
    )


def truth_labels(db: Database, run_id: int | None = None) -> dict[str, TruthLabel]:
    """Label every case of a run (the latest by default) from the ground truth.

    An ACTIVE item is a real alert when its screening pair is a planted true hit, or when one of
    its accounts that belongs to the case's own customer is in a suspicious scenario (any role).
    A case with at least one real alert is SUSPICIOUS, otherwise FALSE_POSITIVE.
    """
    run_id = _latest_run(db)[0] if run_id is None else run_id
    items = _active_items(db, run_id)
    pairs, accounts = _true_pairs(db), _true_items(db, run_id)
    counts: dict[str, list[int]] = {}
    typologies: dict[str, set[str]] = {}
    for r in items.itertuples():
        case_id = str(r.case_id)
        if r.source == "SCREENING":
            found = {t} if (t := pairs.get((str(r.cif), str(r.entry_id)))) else set()
        else:
            found = accounts.get((case_id, str(r.item_key)), set())
        total = counts.setdefault(case_id, [0, 0])
        total[0] += bool(found)
        total[1] += 1
        typologies.setdefault(case_id, set()).update(found)
    return {c: _label(c, n[0], n[1], typologies[c]) for c, n in sorted(counts.items())}


def has_ground_truth(db: Database) -> bool:
    """True when the ground truth holds at least one row (the only other read of that table)."""
    return int(db.query_df("SELECT COUNT(*) FROM ground_truth").iloc[0, 0]) > 0


def _decided_cases(db: Database) -> set[str]:
    df = lower_columns(db.query_df("SELECT case_id FROM case_dispositions"))
    return {str(c) for c in df["case_id"]}


def _selected_groups(groups: dict[str, str], decided: set[str], settings: Settings) -> set[str]:
    """The groups to label: sticky, then topped up to ``ceil(fraction * n)`` in seeded order.

    A group with a decision on any of its cases (simulated or human) stays selected, so a rerun
    does not draw a new share. A decided case that left the run (suppressed, closed away) still
    counts as one selected group of the total, so its disappearance does not free a quota slot.
    Only the missing groups are added, from the seeded permutation of the groups not selected yet.
    With no decision yet this is the first ``take`` of the permutation of all sorted group ids.
    """
    ids = sorted(set(groups.values()))
    fraction = settings.cases.prioritization.simulate_fraction
    gone = len(decided - set(groups))
    take = math.ceil(round(fraction * (len(ids) + gone), 9))  # round first: 0.7 * 10 must give 7
    chosen = {groups[c] for c in decided if c in groups}
    free = [g for g in ids if g not in chosen]
    order = np.random.default_rng(settings.seed).permutation(len(free))
    return chosen | {free[i] for i in order[: max(take - len(chosen) - gone, 0)]}


def simulate_dispositions(db: Database, settings: Settings) -> Simulation:
    """Record a SIMULATED disposition, from the ground truth, on a seeded share of the case groups.

    A case that already has a disposition is skipped. Raises `CaseError` when no case run exists
    and `PrioritizationError` when the ground truth is empty; both before anything is written.
    """
    cfg = settings.cases.prioritization
    run_id, as_of = _latest_run(db)
    if not has_ground_truth(db):
        raise PrioritizationError("no ground truth: nothing to simulate dispositions from")
    groups = case_groups(db, run_id)
    labels = truth_labels(db, run_id)
    decided = _decided_cases(db)
    chosen = _selected_groups(groups, decided, settings)
    done: list[str] = []
    skipped = held_out = 0
    for case_id in sorted(groups):
        if groups[case_id] not in chosen:
            held_out += case_id not in decided
        elif case_id in decided:
            skipped += 1
        else:
            label = labels[case_id]
            record_disposition(
                db, settings, case_id, label.disposition,
                reason=label.reason, actor=cfg.simulated_actor, decided_on=as_of, origin=SIMULATED,
            )  # fmt: skip
            done.append(label.disposition)
    sim = Simulation(
        run_id=run_id,
        groups=len(set(groups.values())),
        labelled_groups=len(chosen),
        labelled=len(done),
        suspicious=done.count(SUSPICIOUS),
        false_positive=done.count(FALSE_POSITIVE),
        held_out=held_out,
        skipped=skipped,
    )
    audit(
        db,
        module="cases",
        entity_type="case_run",
        entity_id=str(run_id),
        decision="DISPOSITIONS_SIMULATED",
        reason=(
            f"Simulated {sim.labelled} disposition(s) from ground truth on "
            f"{sim.labelled_groups} of {sim.groups} case group(s): {sim.suspicious} SUSPICIOUS, "
            f"{sim.false_positive} FALSE_POSITIVE; {sim.skipped} already decided, "
            f"{sim.held_out} left open"
        ),
        version=CASES_VERSION,
        actor=cfg.simulated_actor,
        details=asdict(sim),
    )
    return sim
