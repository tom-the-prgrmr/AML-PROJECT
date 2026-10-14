"""The templated case summary: stored case data laid out as markdown, with no LLM involved.

Column headers are Vietnamese, the same words as the investigator UI; section titles and
prose stay English, like the alert reasons they quote (spec case-summary Q1).

`render_summary` is a pure function of a `CaseView`: no database, no clock, no network, so the
same snapshot always gives the same bytes. It only restates what the case already holds; it never
recommends a disposition.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aml.cases.view import CaseView

SUMMARY_VERSION = "summary/v1"
TEMPLATE_WATERMARK = (
    "TEMPLATE SUMMARY (summary/v1): generated from stored case data without an LLM. "
    "It is not a disposition."
)
SECTION_TITLES = (
    "Subject",
    "Alerts",
    "Priority factors",
    "Activity",
    "Network",
    "Data quality",
    "History",
)
SUBJECT, ALERTS, PRIORITY, ACTIVITY, NETWORK, QUALITY, HISTORY = SECTION_TITLES

_MARKDOWN_SPECIAL = frozenset("\\|`*_[]<>#")
# (key in network.features, how it reads); null values are left out, the order is fixed
_GRAPH_FEATURES = (
    ("in_degree", "in-degree {v}"),
    ("out_degree", "out-degree {v}"),
    ("pagerank_ratio", "PageRank ratio {v:.2f}"),
    ("shared_cluster_id", "shared cluster {v} ({size} customers)"),
    ("is_hub", "hub {yes_no}"),
    ("cycle_alerts", "cycle alerts {v}"),
    ("wcc_size", "component size {v}"),
    ("louvain_size", "community size {v}"),
)


def escape_md(text: object) -> str:
    """Make free text safe inside a markdown table or list item.

    Names, occupations, alert reasons and analyst-typed reasons are untrusted: a `|` would break a
    table and a leading `#` would fake a heading. This protects the markdown structure only; it is
    not a prompt-injection defence.
    """
    if text is None:
        return "-"
    flat = " ".join(str(text).split())  # newlines and runs of blanks become one space
    if not flat:
        return "-"
    return "".join("\\" + ch if ch in _MARKDOWN_SPECIAL else ch for ch in flat)


def _ts(value: Any) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return f"{value:%Y-%m-%d %H:%M:%S}"


def _vnd(value: Any) -> str:
    return f"{int(value):,}"


def _cell(value: Any) -> str:
    """A system-generated value printed as is; `-` when it is missing."""
    return "-" if value is None else str(value)


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return lines + ["| " + " | ".join(row) + " |" for row in rows]


def _header(case: CaseView) -> list[str]:
    linked, kyc = case.enrichment["linked_cifs"], case.enrichment["kyc"]
    by_source = {source: 0 for source in ("RULE", "NETWORK", "SCREENING", "ANOMALY")}
    for alert in case.alerts:
        by_source[alert.source] += 1
    anomaly = f", {by_source['ANOMALY']} ANOMALY" if by_source["ANOMALY"] else ""  # Phase 7b-i
    if case.score is None:
        priority = "not scored"
    else:
        rank = case.score["queue_rank"]
        place = "not in the queue" if rank is None else f"queue rank {rank}"
        priority = f"{case.score['score']:.4f} ({place}, model {case.score['model_version']})"
    decided = case.disposition
    if decided is None:
        disposition = "none"
    else:
        disposition = (
            f"{decided.disposition} on {decided.decided_on:%Y-%m-%d} by "
            f"{escape_md(decided.actor)} ({decided.origin}): {escape_md(decided.reason)}"
        )
    return [
        f"# Case {case.case_id}",
        "",
        f"> {TEMPLATE_WATERMARK}",
        "",
        f"- Status: {case.status}",
        f"- Customer: {case.golden_customer_id} ({len(linked['cifs'])} CIF(s), "
        f"{len(linked['accounts'])} account(s)), KYC risk {kyc['risk_rating'] or 'unknown'}",
        f"- Alerts: {len(case.alerts)} ({by_source['RULE']} RULE, {by_source['NETWORK']} NETWORK, "
        f"{by_source['SCREENING']} SCREENING{anomaly}) between {_ts(case.first_alert_ts)} and "
        f"{_ts(case.last_alert_ts)}",
        f"- Priority: {priority}",
        f"- Disposition: {disposition}",
    ]


def _subject(case: CaseView) -> list[str]:
    """One row per CIF, from the masked customer rows the view carries."""
    rows = [
        [
            str(s["cif"]),
            escape_md(s["full_name"]),
            _cell(s["birth_year"]),
            escape_md(s["nationality"]),
            escape_md(s["occupation"]),
            _cell(s["kyc_risk"]),
            f"{_cell(s['id_type'])} {_cell(s['id_number'])}",
        ]
        for s in sorted(case.subjects, key=lambda subject: subject["cif"])
    ]
    accounts = sorted(case.enrichment["linked_cifs"]["accounts"], key=lambda a: a["account_id"])
    listed = ", ".join(
        f"{a['account_id']} ({_cell(a['account_type'])}, {a['cif']})" for a in accounts
    )
    header = ["CIF", "Họ tên", "Năm sinh", "Quốc tịch", "Nghề nghiệp", "Rủi ro KYC", "Giấy tờ"]
    return [f"## {SUBJECT}", "", *_table(header, rows), "", f"Accounts: {listed or '-'}"]


def _alerts(case: CaseView) -> list[str]:
    rows = [
        [str(n), _ts(alert.event_ts), alert.source, alert.rule_id, escape_md(alert.reason)]
        for n, alert in enumerate(case.alerts, start=1)
    ]
    header = ["#", "Sự kiện đầu", "Nguồn", "Luật", "Lý do"]
    return [f"## {ALERTS}", "", *_table(header, rows)]


def _priority(case: CaseView) -> list[str]:
    if case.score is None:
        return [f"## {PRIORITY}", "", "Not scored yet."]
    rows = [
        [str(f["feature"]), f"{f['value']:g}", f"{f['contribution']:+.2f}"]
        for f in case.score["top_features"]
    ]
    return [f"## {PRIORITY}", "", *_table(["Yếu tố", "Giá trị", "Đóng góp"], rows)]


def _activity(case: CaseView) -> list[str]:
    t = case.enrichment["txn_summary"]
    title = [f"## {ACTIVITY} from {t['window_start']} to {t['window_end']}", ""]
    if t["txn_count"] == 0:
        return [*title, "- No transactions in this window."]
    channels = [
        [channel, str(v["count"]), _vnd(v["vnd"])] for channel, v in sorted(t["by_channel"].items())
    ]
    return [
        *title,
        f"- {t['txn_count']} transaction(s) on {t['active_days']} day(s): {t['in_count']} in "
        f"totalling {_vnd(t['in_vnd'])} VND, {t['out_count']} out totalling "
        f"{_vnd(t['out_vnd'])} VND",
        f"- Cash: {_vnd(t['cash_in_vnd'])} VND in, {_vnd(t['cash_out_vnd'])} VND out",
        f"- {t['counterparties']} counterparty(ies); largest transaction "
        f"{_vnd(t['max_txn_vnd'])} VND",
        "",
        *_table(["Kênh", "Số giao dịch", "VND"], channels),
    ]


def _graph_features(source: str, features: dict[str, Any]) -> str:
    if source == "none":
        return "- Graph features: not available"
    parts = [
        text.format(
            v=features[key],
            size=_cell(features.get("shared_cluster_size")),
            yes_no="yes" if features[key] else "no",
        )
        for key, text in _GRAPH_FEATURES
        if features.get(key) is not None
    ]
    return f"- Graph features ({source}): " + (", ".join(parts) or "none recorded")


def _network(case: CaseView) -> list[str]:
    network = case.enrichment["network"]
    lines = [f"## {NETWORK}", "", _graph_features(network["source"], network["features"])]
    if network["counterparties"]:
        rows = [
            [
                c["account_id"],
                c["golden_customer_id"] or "external",
                c["direction"],
                str(c["txns"]),
                _vnd(c["vnd"]),
            ]
            for c in network["counterparties"]
        ]
        header = ["Đối tác", "Chủ sở hữu", "Chiều tiền", "Số giao dịch", "VND"]
        lines += ["", *_table(header, rows)]
    related = ", ".join(network["shared_alert_cases"]) or "none"
    return [*lines, "", f"- Related cases sharing an alert: {related}"]


def _data_quality(case: CaseView) -> list[str]:
    issues = case.enrichment["dq_issues"]
    lines = [f"- {i['cif']}: {i['rule_id']} ({_cell(i['dimension'])})" for i in issues["customer"]]
    # sorted here: a JSON column does not promise to keep its key order on every backend
    lines += [
        f"- transactions: {rule} x {count}"
        for rule, count in sorted(issues["transactions"].items())
    ]
    return [f"## {QUALITY}", "", *(lines or ["- No data quality issue found."])]


def _history(case: CaseView) -> list[str]:
    history = case.enrichment["history"]
    prior = []
    for p in history["prior_cases"]:
        outcome = (
            "no disposition"
            if p["disposition"] is None
            else f"disposition {p['disposition']} on {p['decided_on']}"
        )
        prior.append(
            f"- Prior case {p['case_id']}: {p['alerts']} alert(s), first alert "
            f"{_ts(p['first_alert_ts'])}, {outcome}"
        )
    return [
        f"## {HISTORY}",
        "",
        *(prior or ["- Prior cases: none"]),
        f"- Auto-cleared screening matches: {history['screening_auto_cleared']}; "
        f"suppressed alerts in this run: {history['suppressed_items']}",
    ]


def render_summary(case: CaseView) -> str:
    """The whole summary: header, the seven sections in `SECTION_TITLES` order, footer."""
    blocks = [
        _header(case),
        _subject(case),
        _alerts(case),
        _priority(case),
        _activity(case),
        _network(case),
        _data_quality(case),
        _history(case),
        ["---", f"Template {SUMMARY_VERSION}; case run {case.run_id}; no LLM was used."],
    ]
    return "\n\n".join("\n".join(block) for block in blocks)
