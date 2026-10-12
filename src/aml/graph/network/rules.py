"""The network rule catalogue and the parameters recorded for each rule in monitoring_runs."""

from __future__ import annotations

from dataclasses import dataclass

from aml.common.config import Settings


@dataclass(frozen=True)
class NetworkRule:
    rule_id: str
    rule_version: str
    target_typology: str  # ground_truth typology the rule aims at
    description: str


NETWORK_RULES: tuple[NetworkRule, ...] = (
    NetworkRule(
        "NET_SHARED_ATTRIBUTE",
        "v1",
        "mule_ring",
        "Customers of one cluster linked by shared device, phone or address",
    ),
    NetworkRule(
        "NET_CYCLE",
        "v1",
        "round_tripping",
        "Money leaving an account and returning to it through other customers within days",
    ),
    NetworkRule(
        "NET_HUB",
        "v1",
        "mule_ring",
        "Account collecting money from many other customers with outsized PageRank",
    ),
)


def network_rule_params(rule_id: str, settings: Settings) -> dict[str, int | float | str]:
    """Typed parameters of one network rule: the config keys the detection actually reads."""
    n = settings.network
    if rule_id == "NET_SHARED_ATTRIBUTE":
        s = n.shared_attributes
        return {
            "max_customers_per_value": s.max_customers_per_value,
            "min_customers": s.min_customers,
        }
    if rule_id == "NET_CYCLE":
        c = n.cycles
        return {
            "max_length": c.max_length,
            "max_search_steps": c.max_search_steps,
            "min_amount_ratio": c.min_amount_ratio,
            "min_amount_vnd": c.min_amount_vnd,
            "min_length": c.min_length,
            "window_hours": c.window_hours,
        }
    if rule_id == "NET_HUB":
        h = n.hubs
        return {
            "lookback_days": h.lookback_days,
            "min_in_degree": h.min_in_degree,
            "min_inflow_vnd": h.min_inflow_vnd,
            "min_pagerank_ratio": h.min_pagerank_ratio,
            "pagerank_alpha": h.pagerank_alpha,
        }
    raise KeyError(f"unknown network rule: {rule_id}")
