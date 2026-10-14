"""Case -> typology links derived deterministically from the alerts of each case (read-only)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from aml.assistant.knowledge.model import SCREENING_LIST_TYPOLOGY
from aml.common.db import Database
from aml.graph.network.rules import NETWORK_RULES
from aml.monitoring.rules import RULES

SOURCE_SCREENING = "SCREENING"


@dataclass(frozen=True)
class TypologyMatch:
    case_id: str
    typology_id: str
    rule_ids: tuple[str, ...]  # ascending, distinct
    alert_keys: tuple[str, ...]  # item_key, ascending
    evidence_ids: tuple[str, ...]  # txn_id and the screening alert_ref, ascending
    reason: str


def rule_typologies() -> dict[str, str]:
    """rule_id -> typology_id for every monitoring / network rule that has a target."""
    mapping = {r.rule_id: r.target_typology for r in RULES if r.target_typology}
    mapping.update({r.rule_id: r.target_typology for r in NETWORK_RULES if r.target_typology})
    return mapping


def _read(db: Database, name: str) -> list[dict[str, Any]]:
    text = db.sql_file(f"assistant/{name}").read_text(encoding="utf-8").strip().rstrip(";")
    df = db.query_df(text)
    df.columns = [str(c).lower() for c in df.columns]
    return df.to_dict("records")


def _list_type(details: Any) -> str | None:
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            return None
    return details.get("list_type") if isinstance(details, dict) else None


def derive_matches(db: Database) -> list[TypologyMatch]:
    """One match per (case, typology), sorted by that pair. Writes nothing."""
    items = _read(db, "case_items.sql")
    if not items:
        return []
    evidence: dict[str, list[str]] = defaultdict(list)
    for row in _read(db, "case_evidence.sql"):
        evidence[str(row["alert_id"])].append(str(row["txn_id"]))
    by_rule = rule_typologies()
    rules: dict[tuple[str, str], set[str]] = defaultdict(set)
    keys: dict[tuple[str, str], set[str]] = defaultdict(set)
    evid: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in items:
        if item["source"] == SOURCE_SCREENING:
            typology = SCREENING_LIST_TYPOLOGY.get(_list_type(item["details"]) or "")
            ids = [str(item["alert_ref"])]
        else:
            typology = by_rule.get(item["rule_id"])
            ids = evidence.get(str(item["alert_ref"]), [])
        if typology is None:
            continue
        pair = (str(item["case_id"]), typology)
        rules[pair].add(str(item["rule_id"]))
        keys[pair].add(str(item["item_key"]))
        evid[pair].update(ids)
    matches = []
    for pair in sorted(rules):
        rule_ids = tuple(sorted(rules[pair]))
        alert_keys = tuple(sorted(keys[pair]))
        reason = (
            f"{len(alert_keys)} alert(s) from rule(s) {', '.join(rule_ids)} "
            f"map to typology {pair[1]}"
        )
        matches.append(
            TypologyMatch(pair[0], pair[1], rule_ids, alert_keys, tuple(sorted(evid[pair])), reason)
        )
    return matches
