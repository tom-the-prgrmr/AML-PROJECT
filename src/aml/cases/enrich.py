"""Case enrichment: the six blocks an investigator needs next to the alerts of a case.

``enrich_cases`` writes one ``case_enrichment`` row per (case, section) for a run. It holds no
PII (names, document numbers, contacts, memos); those are joined at read time by `load_case`.
Reference tables are read once per run, the data quality checks once per table, and the
transaction queries once per case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from aml.cases.enrich_network import choose_source, golden_features, load_features, network_block
from aml.cases.enrich_txn import txn_activity
from aml.cases.items import sql_statement
from aml.cases.values import iso_date, iso_ts, lower_columns, plain, whole
from aml.common.config import Settings
from aml.common.db import Database
from aml.dq.rules import RULES
from aml.dq.runner import failing_ids

_RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
_DIMENSION = {rule.rule_id: rule.dimension for rule in RULES}


@dataclass(frozen=True)
class _Reference:
    """Tables read once per run and looked up per case."""

    golden: pd.DataFrame  # cif, golden_customer_id, cluster_size
    customers: pd.DataFrame  # indexed by cif
    accounts: pd.DataFrame  # account_id, cif, account_type, open_date
    er: pd.DataFrame  # indexed by golden_customer_id: pairs, min_match_weight
    cleared: dict[str, int]  # cif -> AUTO_CLEARED screening rows
    suppressed: dict[str, int]  # golden_customer_id -> SUPPRESSED items of the run
    history: pd.DataFrame  # latest snapshot of every case, with its latest disposition
    dq_customers: dict[str, frozenset[str]]
    dq_txns: dict[str, frozenset[str]]


def _read(db: Database, sql: str) -> pd.DataFrame:
    return lower_columns(db.query_df(sql))


def _reference(db: Database, settings: Settings, run_id: int, as_of: date) -> _Reference:
    customers = _read(
        db,
        "SELECT cif, kyc_risk, occupation, nationality, gender, dob, id_type FROM customers",
    ).set_index("cif")
    cleared = _read(
        db,
        "SELECT cif, COUNT(*) AS n FROM screening_current WHERE decision = 'AUTO_CLEARED' "
        "GROUP BY cif",
    )
    suppressed = _read(
        db,
        "SELECT golden_customer_id, COUNT(*) AS n FROM case_alerts "
        f"WHERE run_id = {run_id} AND status = 'SUPPRESSED' GROUP BY golden_customer_id",
    )
    history = _read(
        db,
        "SELECT c.case_id, c.golden_customer_id, c.window_start, c.first_alert_ts, c.alerts, "
        "d.disposition, d.decided_on FROM cases c "
        "LEFT JOIN case_dispositions_current d ON d.case_id = c.case_id "
        f"WHERE (c.run_id IN (SELECT run_id FROM case_runs) OR c.run_id = {run_id}) "
        "AND c.run_id = (SELECT MAX(x.run_id) FROM cases x WHERE x.case_id = c.case_id "
        f"AND (x.run_id IN (SELECT run_id FROM case_runs) OR x.run_id = {run_id}))",
    )
    history["window_start"] = pd.to_datetime(history["window_start"])
    return _Reference(
        golden=_read(db, "SELECT cif, golden_customer_id, cluster_size FROM customer_golden"),
        customers=customers,
        accounts=_read(
            db,
            "SELECT account_id, cif, account_type, open_date FROM accounts WHERE cif IS NOT NULL",
        ),
        er=_read(
            db, "SELECT golden_customer_id, pairs, min_match_weight FROM er_cluster_weights"
        ).set_index("golden_customer_id"),
        cleared={str(c): whole(n) for c, n in zip(cleared["cif"], cleared["n"], strict=True)},
        suppressed={
            str(g): whole(n)
            for g, n in zip(suppressed["golden_customer_id"], suppressed["n"], strict=True)
        },
        history=history,
        dq_customers=failing_ids(db, settings, as_of=as_of, table_name="customers"),
        dq_txns=failing_ids(db, settings, as_of=as_of, table_name="transactions"),
    )


def _kyc(ref: _Reference, cifs: list[str]) -> dict[str, Any]:
    rows = []
    for cif in cifs:
        if cif not in ref.customers.index:
            continue
        c = ref.customers.loc[cif]
        dob = plain(c["dob"])
        rows.append(
            {
                "cif": cif,
                "kyc_risk": plain(c["kyc_risk"]),
                "occupation": plain(c["occupation"]),
                "nationality": plain(c["nationality"]),
                "gender": plain(c["gender"]),
                "birth_year": None if dob is None else pd.Timestamp(dob).year,
                "id_type": plain(c["id_type"]),
            }
        )
    ranked = [r["kyc_risk"] for r in rows if r["kyc_risk"] in _RISK_ORDER]
    return {
        "risk_rating": max(ranked, key=_RISK_ORDER.__getitem__) if ranked else None,
        "cifs": rows,
    }


def _linked_cifs(ref: _Reference, golden_id: str, cifs: list[str]) -> dict[str, Any]:
    sizes = ref.golden[ref.golden["golden_customer_id"] == golden_id]["cluster_size"]
    accounts = ref.accounts[ref.accounts["cif"].isin(cifs)].sort_values("account_id")
    er = None
    if golden_id in ref.er.index:  # none for a one-CIF cluster (or an ER run without pairs)
        weights = ref.er.loc[golden_id]
        er = {
            "pairs": whole(weights["pairs"]),
            "min_match_weight": plain(weights["min_match_weight"]),
        }
    return {
        "cluster_size": whole(sizes.max()) if len(sizes) else len(cifs),
        "cifs": cifs,
        "accounts": [
            {
                "account_id": str(a.account_id),
                "cif": str(a.cif),
                "account_type": plain(a.account_type),
                "open_date": iso_date(a.open_date),
            }
            for a in accounts.itertuples()
        ],
        "er": er,
    }


def _dq_issues(ref: _Reference, cifs: list[str], txn_ids: frozenset[str]) -> dict[str, Any]:
    customer = [
        {"cif": cif, "rule_id": rule_id, "dimension": _DIMENSION.get(rule_id)}
        for cif in cifs
        for rule_id, failing in ref.dq_customers.items()
        if cif in failing
    ]
    transactions = {
        rule_id: len(failing & txn_ids)
        for rule_id, failing in sorted(ref.dq_txns.items())
        if failing & txn_ids
    }
    return {
        "customer": sorted(customer, key=lambda r: (r["cif"], r["rule_id"])),
        "transactions": transactions,
    }


def _history(ref: _Reference, case: Any, cifs: list[str]) -> dict[str, Any]:
    h = ref.history
    mine = h[
        (h["golden_customer_id"] == case.golden_customer_id)
        & (h["case_id"] != case.case_id)
        & (h["window_start"] < pd.Timestamp(case.window_start))
    ].sort_values(["window_start", "case_id"])
    prior = [
        {
            "case_id": str(p.case_id),
            "first_alert_ts": iso_ts(p.first_alert_ts),
            "alerts": whole(p.alerts),
            "disposition": plain(p.disposition),
            "decided_on": iso_date(p.decided_on),
        }
        for p in mine.itertuples()
    ]
    return {
        "prior_cases": prior,
        "prior_alerts": sum(p["alerts"] for p in prior),
        "screening_auto_cleared": sum(ref.cleared.get(c, 0) for c in cifs),
        "suppressed_items": ref.suppressed.get(str(case.golden_customer_id), 0),
    }


def _shared_cases(active: pd.DataFrame) -> dict[str, list[str]]:
    """case_id -> other cases of the run that share at least one item_key, ascending."""
    by_item = active.groupby("item_key")["case_id"].agg(lambda s: sorted(set(s)))
    shared: dict[str, set[str]] = {}
    for case_ids in by_item:
        for case_id in case_ids:
            shared.setdefault(case_id, set()).update(c for c in case_ids if c != case_id)
    return {case_id: sorted(others) for case_id, others in shared.items()}


def _cifs_of(ref: _Reference, golden_id: str) -> list[str]:
    cifs = ref.golden[ref.golden["golden_customer_id"] == golden_id]["cif"]
    return sorted({str(c) for c in cifs}) or [golden_id.removeprefix("G-")]


def enrich_cases(
    db: Database,
    settings: Settings,
    *,
    run_id: int,
    as_of: date,
    cases: pd.DataFrame,
    active: pd.DataFrame,
) -> str:
    """Write the six enrichment sections of every case of the run; return the graph source."""
    source = choose_source(db, settings.cases.graph_features, as_of)
    if cases.empty:
        return source
    ref = _reference(db, settings, run_id, as_of)
    features = load_features(db, source)
    shared = _shared_cases(active)
    rows = []
    for case in cases.itertuples():
        golden_id, case_id = str(case.golden_customer_id), str(case.case_id)
        cifs = _cifs_of(ref, golden_id)
        accounts = ref.accounts[ref.accounts["cif"].isin(cifs)]["account_id"].astype(str).tolist()
        activity = txn_activity(
            db,
            cifs,
            golden_id,
            case.last_alert_ts,
            days=settings.cases.txn_summary_days,
            top_n=settings.cases.top_counterparties,
        )
        blocks = {
            "kyc": _kyc(ref, cifs),
            "linked_cifs": _linked_cifs(ref, golden_id, cifs),
            "dq_issues": _dq_issues(ref, cifs, activity.txn_ids),
            "txn_summary": activity.summary,
            "network": network_block(
                source,
                golden_features(features, accounts),
                activity.counterparties,
                shared.get(case_id, []),
            ),
            "history": _history(ref, case, cifs),
        }
        for section, content in blocks.items():
            rows.append(
                {
                    "run_id": run_id,
                    "case_id": case_id,
                    "section": section,
                    "content": json.dumps(content, ensure_ascii=False, allow_nan=False),
                }
            )
    _write(db, run_id, pd.DataFrame(rows))
    return source


def _write(db: Database, run_id: int, rows: pd.DataFrame) -> None:
    """Insert the enrichment rows; on Oracle each network row goes in with a float ratio."""
    if db.backend != "oracle" or rows.empty:
        db.insert_df("case_enrichment", rows)
        return
    is_network = rows["section"] == "network"
    db.insert_df("case_enrichment", rows[~is_network])
    statement = sql_statement(db, "cases/network_float.sql")
    network = rows[is_network]
    for case_id, content in zip(network["case_id"], network["content"], strict=True):
        ratio = json.loads(content)["features"]["pagerank_ratio"]
        db.execute(
            statement,
            {"run_id": run_id, "case_id": case_id, "content": content, "ratio": ratio},
        )
