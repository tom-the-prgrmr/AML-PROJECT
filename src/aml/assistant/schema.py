"""The part of the graph that generated Cypher may read (pure Python).

It is an allow-list: the Text2Cypher guard rejects every label, relationship type, property and
function that is not named here. The knowledge chunks, their text and embeddings, and the state
nodes are deliberately absent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class GraphSchema:
    labels: Mapping[str, tuple[str, ...]]  # label -> readable properties
    relationships: Mapping[str, tuple[str, ...]]  # type -> readable properties
    functions: frozenset[str]  # callable function names (matched case-insensitively)

    @property
    def properties(self) -> frozenset[str]:
        """Every readable property, of any label or relationship type."""
        groups = [*self.labels.values(), *self.relationships.values()]
        return frozenset(name for group in groups for name in group)


GRAPH_SCHEMA = GraphSchema(
    labels={
        "Customer": ("golden_customer_id", "cifs", "cif_count"),
        "Account": (
            "account_id",
            "cif",
            "account_type",
            "branch_id",
            "open_date",
            "currency",
            "is_external",
        ),
        "Device": ("key",),
        "Phone": ("key",),
        "Address": ("key",),
        "Case": (
            "case_id",
            "golden_customer_id",
            "status",
            "window_start",
            "first_alert_ts",
            "last_alert_ts",
            "alerts",
            "sources",
        ),
        "Typology": ("typology_id", "name", "rule_ids"),
        "RedFlag": ("red_flag_id", "name"),
        "Procedure": ("procedure_id", "name"),
        "Regulation": ("regulation_id", "name"),
    },
    relationships={
        "OWNS": ("cif",),
        "USES_DEVICE": (),
        "HAS_PHONE": (),
        "LIVES_AT": (),
        "TRANSFERRED_TO": ("txn_id", "amount", "ts", "channel"),
        "SENT_TO": ("day", "count", "total"),
        "ABOUT": (),
        "MATCHES_TYPOLOGY": ("evidence_ids", "alert_keys", "rule_ids", "reason"),
        "HAS_RED_FLAG": (),
        "INVESTIGATED_BY": (),
        "GOVERNED_BY": (),
        "REQUIRED_BY": (),
    },
    functions=frozenset(
        {
            "count", "sum", "avg", "min", "max", "collect", "size", "length", "nodes",
            "relationships", "labels", "type", "coalesce", "head", "last", "abs", "round",
            "toString", "toInteger", "toFloat", "toLower", "toUpper", "date", "datetime",
            "localdatetime", "duration", "duration.between", "duration.inDays", "startNode",
            "endNode", "any", "all", "none", "single",
        }
    ),
)  # fmt: skip

# (source label, relationship type, target label), in the order shown to the model
PATTERNS = (
    ("Customer", "OWNS", "Account"),
    ("Customer", "USES_DEVICE", "Device"),
    ("Customer", "HAS_PHONE", "Phone"),
    ("Customer", "LIVES_AT", "Address"),
    ("Account", "TRANSFERRED_TO", "Account"),
    ("Account", "SENT_TO", "Account"),
    ("Case", "ABOUT", "Customer"),
    ("Case", "MATCHES_TYPOLOGY", "Typology"),
    ("Typology", "HAS_RED_FLAG", "RedFlag"),
    ("Typology", "INVESTIGATED_BY", "Procedure"),
    ("Typology", "GOVERNED_BY", "Regulation"),
    ("Procedure", "REQUIRED_BY", "Regulation"),
)
NOTES = (
    "TRANSFERRED_TO is one transfer; ts is a LOCAL DATETIME, amount is whole VND.",
    "SENT_TO is one day of transfers between two accounts; day is a DATE, total is whole VND.",
    "An Account with is_external = true is outside the bank and has no owner.",
)


def _props(names: tuple[str, ...]) -> str:
    return " {" + ", ".join(names) + "}" if names else ""


def schema_text(schema: GraphSchema = GRAPH_SCHEMA) -> str:
    """The schema description that goes into the Text2Cypher prompt."""
    lines = ["Node labels and their properties:"]
    lines += [f"- {label}{_props(props)}" for label, props in schema.labels.items()]
    lines.append("Relationships and their properties:")
    shown = set()
    for source, rel, target in PATTERNS:
        if rel in schema.relationships:
            shown.add(rel)
            lines.append(f"- (:{source})-[:{rel}{_props(schema.relationships[rel])}]->(:{target})")
    lines += [
        f"- [:{rel}{_props(props)}]"
        for rel, props in schema.relationships.items()
        if rel not in shown
    ]
    lines += [f"Note: {note}" for note in NOTES]
    return "\n".join(lines)
