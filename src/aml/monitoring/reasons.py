"""Human-readable `reason` text of each monitoring rule (stored on the alert and in audit_log)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

_TS = "%Y-%m-%d %H:%M:%S"


def _span(start: datetime, end: datetime) -> str:
    return f"between {start.strftime(_TS)} and {end.strftime(_TS)}"


def build_reason(
    rule_id: str,
    metrics: Mapping[str, int],
    params: Mapping[str, int | float | str],
    start: datetime,
    end: datetime,
) -> str:
    """Explain one detection from its SQL metrics and the parameters that produced it."""
    m, p, span = metrics, params, _span(start, end)
    if rule_id == "STRUCTURING":
        return (
            f"{m['deposits']} cash deposits of {int(p['band_low_vnd']):,} to "
            f"{int(p['large_cash_vnd']) - 1:,} VND (just under the {int(p['large_cash_vnd']):,} "
            f"VND reporting threshold) totalling {m['total_vnd']:,} VND at {m['branches']} "
            f"branch(es) {span}"
        )
    if rule_id == "RAPID_MOVEMENT":
        share = m["out_vnd"] / m["in_vnd"]
        return (
            f"received {m['in_vnd']:,} VND and sent out {m['out_vnd']:,} VND ({share:.0%}) {span}"
        )
    if rule_id == "HIGH_VELOCITY":
        return (
            f"{m['txns']} transactions totalling {m['total_vnd']:,} VND {span} (at least "
            f"{p['min_txns']} within {p['window_hours']} hours; counterparties known for "
            f"{p['known_counterparty_days']}+ days excluded)"
        )
    if rule_id in ("FAN_IN", "FAN_OUT"):
        verb, who = ("received", "senders") if rule_id == "FAN_IN" else ("sent", "receivers")
        prep = "from" if rule_id == "FAN_IN" else "to"
        return (
            f"{verb} {m['total_vnd']:,} VND {prep} {m['counterparties']} new {who} in "
            f"{m['txns']} transactions {span} (at least {p['min_counterparties']} within "
            f"{p['window_days']} days)"
        )
    if rule_id == "DORMANT_REACTIVATION":
        return (
            f"no activity for {m['quiet_days']} days, then {m['txns']} transaction(s) totalling "
            f"{m['total_vnd']:,} VND {span} (window {p['window_hours']} hours)"
        )
    raise KeyError(f"unknown monitoring rule: {rule_id}")
