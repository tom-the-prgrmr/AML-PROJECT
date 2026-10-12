"""The monitoring rule catalogue and the parameters substituted into each rule's SQL file."""

from __future__ import annotations

import math
from dataclasses import dataclass

from aml.common.config import Settings


@dataclass(frozen=True)
class MonitoringRule:
    rule_id: str
    rule_version: str
    sql_file: str  # e.g. "monitoring/structuring.sql"
    target_typology: str | None  # ground_truth typology the rule aims at, if any
    description: str


RULES: tuple[MonitoringRule, ...] = (
    MonitoringRule(
        "STRUCTURING",
        "v1",
        "monitoring/structuring.sql",
        "structuring",
        "Repeated cash deposits just under the large-cash reporting threshold",
    ),
    MonitoringRule(
        "RAPID_MOVEMENT",
        "v1",
        "monitoring/rapid_movement.sql",
        "rapid_movement",
        "Large inflow passed out again within hours",
    ),
    MonitoringRule(
        "HIGH_VELOCITY",
        "v1",
        "monitoring/high_velocity.sql",
        None,
        "Unusually many transactions with new counterparties in a short window",
    ),
    MonitoringRule(
        "FAN_IN",
        "v1",
        "monitoring/fan_in_out.sql",
        "mule_ring",
        "Many new senders paying one account within days",
    ),
    MonitoringRule(
        "FAN_OUT",
        "v1",
        "monitoring/fan_in_out.sql",
        "mule_ring",
        "One account paying many new receivers within days",
    ),
    MonitoringRule(
        "DORMANT_REACTIVATION",
        "v1",
        "monitoring/dormant_reactivation.sql",
        None,
        "Long-quiet account suddenly moving a large amount",
    ),
)


def rule_params(rule_id: str, settings: Settings) -> dict[str, int | float | str]:
    """Typed parameters of one rule: exactly the placeholders its SQL file uses."""
    m = settings.monitoring
    known = m.known_counterparty_days
    if rule_id == "STRUCTURING":
        cap = settings.thresholds.large_cash_vnd
        # round() first: cap * (1 - pct) can land a hair above an integer in float arithmetic
        low = math.ceil(round(cap * (1 - settings.thresholds.structuring_band_pct), 3))
        return {
            "band_low_vnd": low,
            "large_cash_vnd": cap,
            "min_deposits": m.structuring.min_deposits,
            "window_days": m.structuring.window_days,
        }
    if rule_id == "RAPID_MOVEMENT":
        r = m.rapid_movement
        return {
            "window_hours": r.window_hours,
            "min_inflow_vnd": r.min_inflow_vnd,
            "min_pass_through_pct": r.min_pass_through_pct,
        }
    if rule_id == "HIGH_VELOCITY":
        v = m.high_velocity
        return {
            "window_hours": v.window_hours,
            "min_txns": v.min_txns,
            "min_total_vnd": v.min_total_vnd,
            "known_counterparty_days": known,
        }
    if rule_id in ("FAN_IN", "FAN_OUT"):
        f = m.fan_in_out
        return {
            "direction": "IN" if rule_id == "FAN_IN" else "OUT",
            "window_days": f.window_days,
            "min_counterparties": f.min_counterparties,
            "min_total_vnd": f.min_total_vnd,
            "known_counterparty_days": known,
        }
    if rule_id == "DORMANT_REACTIVATION":
        d = m.dormant_reactivation
        return {
            "dormant_days": d.dormant_days,
            "window_hours": d.window_hours,
            "min_amount_vnd": d.min_amount_vnd,
        }
    raise KeyError(f"unknown monitoring rule: {rule_id}")
