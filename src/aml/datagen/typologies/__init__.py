"""Typology injection (spec 1b-ii): suspicious scenarios, benign look-alikes and their labels.

``inject_typologies`` picks scenario accounts from a shuffled pool (one CURRENT account per real
person, each used at most once), builds every scenario's evidence transactions with the typology
builders, and returns them together with a customers copy in which mule-ring members share
attributes. ``ground_truth_records`` turns the scenarios plus the final ``txn_id`` values into
``ground_truth`` rows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from aml.datagen.typologies._common import AccountPool, Scenario, TypologyContext, rows_frame
from aml.datagen.typologies.benign import build_benign_merchant, build_benign_payroll
from aml.datagen.typologies.mule_ring import build_mule_ring, link_members
from aml.datagen.typologies.rapid_movement import build_rapid_movement
from aml.datagen.typologies.round_tripping import build_round_tripping
from aml.datagen.typologies.structuring import build_structuring

__all__ = [
    "SCENARIO_PREFIX",
    "Scenario",
    "TypologyContext",
    "TypologyResult",
    "ground_truth_records",
    "inject_typologies",
]

Builder = Callable[[TypologyContext, AccountPool, np.random.Generator, str], Scenario]
# Build order is fixed so the same seed yields the same scenarios.
BUILDERS: dict[str, Builder] = {
    "structuring": build_structuring,
    "rapid_movement": build_rapid_movement,
    "mule_ring": build_mule_ring,
    "round_tripping": build_round_tripping,
    "benign_payroll": build_benign_payroll,
    "benign_merchant": build_benign_merchant,
}
SCENARIO_PREFIX = {
    "structuring": "STR",
    "rapid_movement": "RAP",
    "mule_ring": "MULE",
    "round_tripping": "RND",
    "benign_payroll": "PAY",
    "benign_merchant": "MER",
    "prompt_injection": "INJ",
}
SCENARIO_TAG = "_scenario"  # private column on typology rows; dropped before output


@dataclass(frozen=True)
class TypologyResult:
    """Everything the activity generator needs from the injection step."""

    scenarios: list[Scenario]
    rows: pd.DataFrame  # all evidence rows plus the SCENARIO_TAG column
    customers: pd.DataFrame  # copy of the input with mule-ring attributes overwritten

    @property
    def accounts(self) -> frozenset[str]:
        """Every account that belongs to a scenario."""
        return frozenset(a for s in self.scenarios for a, _ in s.accounts)


def scenario_id(typology: str, number: int) -> str:
    """Return ``GT-<PREFIX>-<number:04d>``."""
    return f"GT-{SCENARIO_PREFIX[typology]}-{number:04d}"


def _build_pool(
    accounts: pd.DataFrame, customer_person: pd.DataFrame, rng: np.random.Generator
) -> AccountPool:
    """Shuffle one CURRENT account per person_id (the first by cif)."""
    current = accounts.loc[accounts["account_type"] == "CURRENT", ["account_id", "cif"]]
    merged = current.merge(customer_person[["cif", "person_id"]], on="cif")
    merged = merged.sort_values(["person_id", "cif"], kind="stable")
    merged = merged.drop_duplicates("person_id").sort_values("account_id").reset_index(drop=True)
    ids = merged["account_id"].to_numpy(dtype=object)[rng.permutation(len(merged))]
    return AccountPool(ids.tolist(), dict(zip(merged["account_id"], merged["cif"], strict=True)))


def inject_typologies(
    accounts: pd.DataFrame,
    customers: pd.DataFrame,
    customer_person: pd.DataFrame,
    counts: dict[str, int],
    ctx: TypologyContext,
    rng: np.random.Generator,
) -> TypologyResult:
    """Build ``counts[typology]`` scenarios per typology on the ``ground_truth`` sub-stream.

    Raises ``ValueError`` ("not enough accounts") when the scenarios need more distinct-person
    CURRENT accounts than exist. ``customers`` is never modified.
    """
    pool = _build_pool(accounts, customer_person, rng)
    scenarios: list[Scenario] = []
    for typology, builder in BUILDERS.items():
        for number in range(1, counts.get(typology, 0) + 1):
            scenarios.append(builder(ctx, pool, rng, scenario_id(typology, number)))
    linked = customers.copy()
    for scenario in scenarios:
        if scenario.linked_cifs:
            link_members(linked, scenario.linked_cifs, rng)
    tagged = []
    for scenario in scenarios:
        rows = scenario.rows.copy()
        rows[SCENARIO_TAG] = scenario.scenario_id
        tagged.append(rows)
    rows = pd.concat(tagged, ignore_index=True) if tagged else rows_frame([])
    if not tagged:
        rows[SCENARIO_TAG] = pd.Series(dtype=object)
    return TypologyResult(scenarios=scenarios, rows=rows, customers=linked)


def _record(
    s: Scenario, start: pd.Timestamp, end: pd.Timestamp, kind: str, entity: str, role: str,
    reason: str,
) -> dict[str, object]:  # fmt: skip
    """One ground_truth row of scenario ``s``."""
    return {
        "scenario_id": s.scenario_id, "typology": s.typology, "is_suspicious": s.is_suspicious,
        "entity_type": kind, "entity_id": entity, "role": role, "start_ts": start,
        "end_ts": end, "reason": reason,
    }  # fmt: skip


def ground_truth_records(
    scenarios: list[Scenario], transactions: pd.DataFrame, injected: pd.DataFrame
) -> list[dict[str, object]]:
    """Return ``ground_truth`` rows (dicts) for ``scenarios`` and the planted injection memos.

    ``transactions`` has ``txn_id``, ``txn_ts`` and the SCENARIO_TAG column; ``injected`` is
    the subset of rows whose memo carries a prompt-injection phrase.
    """
    records: list[dict[str, object]] = []
    tags = transactions[SCENARIO_TAG]
    for s in scenarios:
        evidence = transactions[tags == s.scenario_id]
        start, end = evidence["txn_ts"].min(), evidence["txn_ts"].max()

        for account_id, role in s.accounts:
            records.append(
                _record(s, start, end, "account", account_id, role, f"{role} in: {s.reason}")
            )
        for txn_id in evidence["txn_id"]:
            records.append(_record(s, start, end, "transaction", txn_id, "evidence", s.reason))
    for number, (txn_id, ts) in enumerate(
        zip(injected["txn_id"], injected["txn_ts"], strict=True), start=1
    ):
        records.append(
            {
                "scenario_id": scenario_id("prompt_injection", number),
                "typology": "prompt_injection",
                "is_suspicious": False,
                "entity_type": "transaction",
                "entity_id": txn_id,
                "role": "memo",
                "start_ts": ts,
                "end_ts": ts,
                "reason": "memo carries a prompt-injection phrase aimed at an LLM analyst",
            }
        )
    return records
