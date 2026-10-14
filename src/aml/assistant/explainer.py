"""Typology explainer: "why does this case match structuring?", from stored facts only.

No text is generated, so nothing can be made up: for each typology a case's rule / network alerts
target, it lists the rules (with their version, description and run parameters), the evidence
transactions of those alerts, and the knowledge chunks 8b finds for the typology. The language model
is only used through 8b's `knowledge` for embeddings, never for chat. It writes nothing, not even an
audit row: it is a read like Phase 7's template summary.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import pandas as pd

from aml.assistant import answering, narrative
from aml.assistant.answering import AssistantInputError, citation_dict
from aml.assistant.citations import Citation, to_citation
from aml.assistant.evidence import Evidence, parse_citation
from aml.assistant.llm import LLMClient
from aml.assistant.narrative import Knowledge, knowledge_errors
from aml.cases.values import plain
from aml.cases.view import CaseAlert, load_case
from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.network.rules import NETWORK_RULES
from aml.monitoring.rules import RULES

ALERT_SOURCES = ("RULE", "NETWORK")
DESCRIPTIONS = {r.rule_id: r.description for r in (*RULES, *NETWORK_RULES)}
TYPOLOGY_OF = {r.rule_id: r.target_typology for r in (*RULES, *NETWORK_RULES) if r.target_typology}
TYPOLOGIES = tuple(sorted(set(TYPOLOGY_OF.values())))
TXN_KEYS = ("txn_id", "txn_ts", "from_account_id", "to_account_id", "amount_vnd", "channel")


@dataclass(frozen=True)
class TypologyMatch:
    typology: str
    rule_ids: tuple[str, ...]  # ascending
    definition: str  # one line per rule: "<rule_id> <version>: <description> (<k>=<v>, ...)"
    transactions: tuple[dict[str, Any], ...]  # TXN_KEYS, by (txn_ts, txn_id); no memo, no names
    transactions_total: int  # before the explain_max_transactions cut
    chunks: tuple[dict[str, Any], ...]  # chunk_id, title, excerpt
    citations: tuple[Citation, ...]  # transactions, then chunks; n = 1..k

    def as_dict(self) -> dict[str, Any]:
        return {
            "typology": self.typology,
            "rule_ids": list(self.rule_ids),
            "definition": self.definition,
            "transactions": [dict(t) for t in self.transactions],
            "chunks": [dict(c) for c in self.chunks],
            "citations": [citation_dict(c) for c in self.citations],
        }


@dataclass(frozen=True)
class Explanation:
    case_id: str
    typologies: tuple[TypologyMatch, ...]  # by typology
    knowledge: str  # "ok" | "unavailable"

    def as_dict(self) -> dict[str, Any]:
        """The explainer shape of the UI contract."""
        return {"case_id": self.case_id, "typologies": [t.as_dict() for t in self.typologies]}


# ---------------------------------------------------------------- reads
def _read(db: Database, name: str, alert_ids: list[int]) -> list[dict[str, Any]]:
    """Rows of ``assistant/<name>.sql`` for integer alert ids, as dicts with lower-case keys."""
    text = db.sql_file(f"assistant/{name}.sql").read_text(encoding="utf-8").strip().rstrip(";")
    statement = text.replace("{alert_ids}", ", ".join(str(int(i)) for i in alert_ids))
    frame = db.query_df(statement)
    frame.columns = [str(c).lower() for c in frame.columns]
    return [{k: plain(v) for k, v in row.items()} for row in frame.to_dict("records")]


def _params(value: Any) -> dict[str, Any]:
    parsed = json.loads(value) if isinstance(value, str) else value
    return dict(parsed) if isinstance(parsed, dict) else {}


def _definition(rule_id: str, rows: list[dict[str, Any]]) -> str:
    """One line for a rule, with the parameters of the latest run that raised one of the alerts."""
    latest = max(rows, key=lambda r: int(r["run_id"]))
    line = f"{rule_id} {latest['rule_version']}: {DESCRIPTIONS.get(rule_id, '')}".rstrip()
    params = _params(latest["params"])
    if params:
        line += " (" + ", ".join(f"{k}={params[k]}" for k in sorted(params)) + ")"
    return line


def _transaction(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "txn_id": str(row["txn_id"]),
        "txn_ts": pd.Timestamp(row["txn_ts"]).to_pydatetime().isoformat(),
        "from_account_id": row["from_account_id"],
        "to_account_id": row["to_account_id"],
        "amount_vnd": int(row["amount_vnd"]),
        "channel": row["channel"],
    }


def _txn_citation(txn: dict[str, Any], n: int) -> Citation:
    accounts = (txn["from_account_id"], txn["to_account_id"])
    return Citation(
        n=n,
        kind="transaction",
        id=txn["txn_id"],
        label=f"transaction {txn['txn_id']}",
        node_ids=tuple(dict.fromkeys(a for a in accounts if a is not None)),
        txn_ids=(txn["txn_id"],),
        excerpt=None,
    )


def _chunk(evidence: Evidence) -> dict[str, Any]:
    return {
        "chunk_id": parse_citation(evidence.citations[0])[1],
        "title": evidence.text,
        "excerpt": next((u.text for u in evidence.untrusted if u.field == "chunk_text"), None),
    }


# ---------------------------------------------------------------- the explainer
class _Chunks:
    """Knowledge chunks per typology; the first failure marks the layer unavailable."""

    def __init__(self, settings: Settings, llm: LLMClient, search: Knowledge) -> None:
        self.settings, self.llm, self.search = settings, llm, search
        self.status = "ok"

    def __call__(self, typology: str) -> list[Evidence]:
        limit = self.settings.assistant.answering.explain_chunks
        if self.status != "ok" or limit == 0:
            return []
        query = f"What is the {typology} typology, its red flags and how to investigate it?"
        try:
            found = self.search(
                self.settings, query, llm=self.llm, expand=True, seed_typologies=(typology,)
            )
        except knowledge_errors():
            self.status = "unavailable"
            return []
        chunks = [e for e in found if e.citations and e.citations[0].startswith("chunk:")]
        return chunks[:limit]


def _match(
    typology: str,
    alerts: list[CaseAlert],
    rules: dict[int, dict[str, Any]],
    txns: dict[int, list[dict[str, Any]]],
    chunks: list[Evidence],
    limit: int,
) -> TypologyMatch:
    ids = [int(a.alert_ref) for a in alerts]
    rule_ids = tuple(sorted({a.rule_id for a in alerts}))
    rows_of = defaultdict(list)
    for i in ids:
        if i in rules:
            rows_of[rules[i]["rule_id"]].append(rules[i])
    definition = "\n".join(_definition(r, rows_of[r]) for r in rule_ids if rows_of[r])
    unique = {t["txn_id"]: t for i in ids for t in txns.get(i, [])}
    ordered = sorted(unique.values(), key=lambda t: (t["txn_ts"], t["txn_id"]))
    shown = ordered[:limit]
    citations = [_txn_citation(t, n) for n, t in enumerate(shown, start=1)]
    citations += [to_citation(e, n) for n, e in enumerate(chunks, start=len(shown) + 1)]
    return TypologyMatch(
        typology=typology,
        rule_ids=rule_ids,
        definition=definition,
        transactions=tuple(shown),
        transactions_total=len(ordered),
        chunks=tuple(_chunk(e) for e in chunks),
        citations=tuple(citations),
    )


def explain_typology(
    db: Database,
    settings: Settings,
    case_id: str,
    *,
    typology: str | None = None,
    llm: LLMClient | None = None,
    knowledge: Knowledge | None = None,
) -> Explanation:
    """Why the case matches each typology its alerts target (or only ``typology``).

    Raises `AssistantInputError` for a typology no rule targets and `CaseError` for an unknown case.
    """
    if typology is not None and typology not in TYPOLOGIES:
        raise AssistantInputError(
            f"unknown typology '{typology}'; available: {', '.join(TYPOLOGIES)}"
        )
    case = load_case(db, case_id, masked=True, scored=False)
    by_typology: dict[str, list[CaseAlert]] = defaultdict(list)
    for alert in case.alerts:
        target = TYPOLOGY_OF.get(alert.rule_id)
        if alert.source in ALERT_SOURCES and target and alert.alert_ref.isdigit():
            by_typology[target].append(alert)
    wanted = sorted(t for t in by_typology if typology is None or t == typology)
    if not wanted:
        return Explanation(case_id, (), "ok")
    ids = sorted({int(a.alert_ref) for t in wanted for a in by_typology[t]})
    rules = {int(r["alert_id"]): r for r in _read(db, "explain_rules", ids)}
    txns: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in _read(db, "explain_transactions", ids):
        txns[int(row["alert_id"])].append(_transaction(row))
    client = llm if llm is not None else answering.default_llm(settings)
    search = knowledge if knowledge is not None else narrative.default_knowledge(settings)
    chunks_of = _Chunks(settings, client, search)
    limit = settings.assistant.answering.explain_max_transactions
    matches = tuple(_match(t, by_typology[t], rules, txns, chunks_of(t), limit) for t in wanted)
    return Explanation(case_id, matches, chunks_of.status)
