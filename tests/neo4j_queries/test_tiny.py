"""AC4 and AC6 for specs/neo4j-queries.md on TINY (DuckDB) against a real Neo4j.

TINY is synced once per module. The CLI tests point `aml` at the same DuckDB file.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from tests.graph.helpers import HUB, MULE, PAYROLL, RAP, RND, RND_CYCLE
from tests.neo4j_sync.helpers import s11
from tests.network.helpers import has, of_rule

from .helpers import (
    TINY_S11,
    Synced,
    cli,
    graph_audit,
    mod,
    query,
    rows,
    set_env,
    synced_db,
    trace,
)

pytestmark = pytest.mark.neo4j

SHR = "SHARED-CIF00000002"
SHR_CUSTOMER = "G-CIF00000002"
CYCLE_STEPS = "T0000002197>T0000002246>T0000002299>T0000002327"
FAN_COLUMNS = [
    "account_id",
    "window_start",
    "window_end",
    "counterparties",
    "transfers",
    "total_vnd",
]

# (account, hops, hours, extra kwargs, expected rows)
CASES: list[tuple[str, int, int, dict[str, Any], int]] = [
    (RND, 4, 168, {}, 4),
    (RND, 4, 72, {}, 2),
    (RND, 3, 168, {}, 3),
    (RAP, 2, 24, {}, 4),
    (MULE, 4, 168, {}, 104),
    (HUB, 6, 168, {}, 41),
    (PAYROLL, 2, 24, {}, 120),
    (PAYROLL, 2, 24, {"since": datetime(2026, 6, 1)}, 20),
    (HUB, 6, 720, {}, 65),
]


@pytest.fixture(scope="module")
def tiny(er_template: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Synced]:
    path = tmp_path_factory.mktemp("nq_tiny") / "tiny.duckdb"
    with synced_db(path, template=er_template, expect_graph=s11(*TINY_S11)) as env:
        yield env


@pytest.fixture(scope="module")
def monitored(tiny: Synced) -> Any:
    """`run_monitoring` has run on TINY; returns the network detections."""
    mod("aml.monitoring.runner").run_monitoring(tiny.db, tiny.settings)
    return mod("aml.graph.network.runner").detect_network(tiny.db, tiny.settings)


@pytest.fixture
def tiny_cli(tiny: Synced, monkeypatch: pytest.MonkeyPatch) -> Synced:
    set_env(monkeypatch, {"DB_BACKEND": "duckdb", "AML__DB__DUCKDB_PATH": str(tiny.db.path)})
    return tiny


def _pair(tiny: Synced, account: str, hops: int, hours: int, **kw: Any) -> tuple[Any, Any]:
    args = {"hops": hops, "hours": hours, "record_audit": False, **kw}
    neo = trace(tiny.db, tiny.settings, account, method="neo4j", **args)
    raw = trace(tiny.db, tiny.settings, account, method="cte_raw", **args)
    return neo, raw


# ---------------------------------------------------------------------------------- AC4
@pytest.mark.parametrize(
    ("account", "hops", "hours", "kw", "expected"),
    CASES,
    ids=[f"{a}-{h}-{t}-{'since' if k else 'plain'}" for a, h, t, k, _ in CASES],
)
def test_ac4_neo4j_equals_cte_raw(
    tiny: Synced, account: str, hops: int, hours: int, kw: dict[str, Any], expected: int
) -> None:
    neo, raw = _pair(tiny, account, hops, hours, **kw)
    assert neo.n_paths == expected
    pd.testing.assert_frame_equal(neo.paths, raw.paths)


def test_ac4_round_tripping_cycle_row(tiny: Synced) -> None:
    neo, _ = _pair(tiny, RND, 4, 168)
    last = neo.paths.iloc[-1]
    assert last["path"] == RND_CYCLE
    assert last["step_path"] == CYCLE_STEPS
    assert int(last["amount_vnd"]) == 399_475_000
    assert pd.Timestamp(last["last_ts"]) == pd.Timestamp("2026-03-27 00:11:51")
    assert bool(last["is_cycle"]) is True
    assert neo.n_cycles == 1
    assert neo.n_accounts == 3


def test_ac4_counts_of_accounts_and_cycles(tiny: Synced) -> None:
    mule, _ = _pair(tiny, MULE, 4, 168)
    assert (mule.n_accounts, mule.n_cycles) == (24, 0)
    assert _pair(tiny, HUB, 6, 168)[0].n_cycles == 4
    assert _pair(tiny, HUB, 6, 720)[0].n_cycles == 16


def test_ac4_query_lines_do_not_grow_with_hops(tiny: Synced) -> None:
    short, _ = _pair(tiny, RND, 2, 168)
    long, _ = _pair(tiny, RND, 6, 168)
    assert short.query_lines == long.query_lines > 0


def test_ac4_cli_trace_neo4j(tiny_cli: Synced) -> None:
    result = cli("trace", "--account", RND, "--hops", "4", "--hours", "168", "--method", "neo4j")
    assert result.exit_code == 0, result.output
    summary = [ln for ln in result.stdout.splitlines() if has(ln, "method=neo4j")]
    assert len(summary) == 1
    for token in (
        "backend=duckdb",
        f"account={RND}",
        "hops=4",
        "hours=168",
        "paths=4",
        "accounts=3",
        "cycles=1",
    ):
        assert has(summary[0], token), summary[0]
    cycle_lines = [ln for ln in result.stdout.splitlines() if RND_CYCLE in ln]
    assert len(cycle_lines) == 1
    assert "CYCLE" in cycle_lines[0]


def test_ac4_cli_trace_method_all(tiny_cli: Synced) -> None:
    result = cli("trace", "--account", RND, "--hops", "4", "--hours", "168", "--method", "all")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    for method in ("cte_raw", "cte_edge", "neo4j"):
        assert len([ln for ln in lines if has(ln, f"method={method}")]) == 1, method
    neo_line = next(ln for ln in lines if has(ln, "method=neo4j"))
    assert has(neo_line, "paths=4")
    assert len([ln for ln in lines if "method=pgq skipped: Oracle only" in ln]) == 1


# ---------------------------------------------------------------------------------- AC6
def _alert_rows(db: Any, rule: str) -> pd.DataFrame:
    return db.query_df(
        "SELECT subject_id, window_start, window_end, txn_count, amount_vnd "
        f"FROM alerts_current WHERE rule_id = '{rule}' ORDER BY subject_id"
    )


def test_ac6_cycles_match_net_cycle_alerts(tiny: Synced, monitored: Any) -> None:
    result = query(tiny.db, tiny.settings, "cycles")
    columns = ["length", "path", "step_path", "first_ts", "last_ts", "first_vnd", "last_vnd"]
    assert rows(result, columns) == [
        (
            4,
            "A8201784530>A3312263346>A9950029109>A1070944972",
            CYCLE_STEPS,
            pd.Timestamp("2026-03-22 15:00:00"),
            pd.Timestamp("2026-03-27 00:11:51"),
            456_916_000,
            399_475_000,
        ),
        (
            4,
            "A9059982551>A4750305205>A7799247681>A7641423153",
            "T0000002277>T0000002283>T0000002332>T0000002400",
            pd.Timestamp("2026-03-25 09:00:00"),
            pd.Timestamp("2026-03-29 07:14:22"),
            394_196_000,
            364_863_000,
        ),
    ]
    got = {frozenset(s.split(">")) for s in result.rows["step_path"]}
    alerts = of_rule(monitored, "NET_CYCLE")
    assert len(alerts) == 2
    assert got == {frozenset(a.txn_ids) for a in alerts}
    assert result.n_rows == 2


def test_ac6_cycles_filter_by_account(tiny: Synced) -> None:
    assert query(tiny.db, tiny.settings, "cycles", account="A3312263346").n_rows == 1
    assert query(tiny.db, tiny.settings, "cycles", account="A0000000000").n_rows == 0


def test_ac6_shared_attributes(tiny: Synced) -> None:
    result = query(tiny.db, tiny.settings, "shared_attributes")
    assert rows(result, ["kind", "key", "customers"]) == [
        ("device", "7fa855e04f72697f", 16),
        ("address", "fbe8ded33cfd1ddf", 8),
        ("phone", "387a8bacf21702c0", 7),
        ("address", "7d05ac1a241d4789", 2),
    ]


def test_ac6_shared_cluster_equals_the_shared_attribute_alert(tiny: Synced, monitored: Any) -> None:
    result = query(tiny.db, tiny.settings, "shared_cluster", customer=SHR_CUSTOMER)
    assert result.n_rows == 28
    by_distance = result.rows["distance"].value_counts().to_dict()
    assert {int(k): int(v) for k, v in by_distance.items()} == {1: 15, 2: 13}
    members = set(result.rows["customer"]) | {SHR_CUSTOMER}
    assert len(members) == 29

    alert = next(a for a in of_rule(monitored, "NET_SHARED_ATTRIBUTE") if a.subject_id == SHR)
    details = alert.details if isinstance(alert.details, dict) else json.loads(alert.details)
    assert details["customers"] == 29
    golden = tiny.db.query_df(
        "SELECT cif, golden_customer_id FROM er_golden "
        "WHERE run_id = (SELECT MAX(run_id) FROM er_golden)"
    ).set_index("cif")["golden_customer_id"]
    assert members == {golden[cif] for cif in details["cifs"]}


def test_ac6_fan_in_matches_the_fan_in_alert(tiny: Synced, monitored: Any) -> None:
    result = query(tiny.db, tiny.settings, "fan_in")
    assert rows(result, FAN_COLUMNS) == [
        (
            "A4937939209",
            pd.Timestamp("2026-04-13 09:28:12"),
            pd.Timestamp("2026-04-17 23:16:36"),
            31,
            31,
            2_930_380_000,
        )
    ]
    alert = _alert_rows(tiny.db, "FAN_IN")
    assert list(alert["subject_id"]) == ["A4937939209"]
    row = alert.iloc[0]
    assert pd.Timestamp(row["window_start"]) == pd.Timestamp("2026-04-13 09:28:12")
    assert pd.Timestamp(row["window_end"]) == pd.Timestamp("2026-04-17 23:16:36")
    assert int(row["txn_count"]) == 31
    assert int(row["amount_vnd"]) == 2_930_380_000


def test_ac6_fan_out_is_a_superset_of_the_fan_out_alerts(tiny: Synced, monitored: Any) -> None:
    result = query(tiny.db, tiny.settings, "fan_out")
    assert rows(result, ["account_id", "counterparties", "total_vnd"]) == [
        ("A9075004254", 24, 933_113_000),
        ("A5040436031", 22, 721_737_000),
        ("A2582841008", 21, 751_347_000),
        ("A2697723835", 20, 601_193_000),
        ("A3906301972", 20, 493_277_000),
    ]
    alerts = set(_alert_rows(tiny.db, "FAN_OUT")["subject_id"])
    assert len(alerts) == 4
    found = set(result.rows["account_id"])
    assert alerts <= found
    assert found - alerts == {PAYROLL}
    payroll = result.rows[result.rows["account_id"] == PAYROLL].iloc[0]
    assert pd.Timestamp(payroll["window_start"]) == pd.Timestamp("2026-01-05 08:05:00")


def test_ac6_fan_out_and_fan_in_for_one_account(tiny: Synced) -> None:
    out = query(tiny.db, tiny.settings, "fan_out", account=MULE)
    assert rows(out, FAN_COLUMNS) == [
        (
            MULE,
            pd.Timestamp("2026-04-13 02:50:10"),
            pd.Timestamp("2026-04-15 18:06:40"),
            21,
            21,
            751_347_000,
        )
    ]
    assert query(tiny.db, tiny.settings, "fan_in", account=MULE).n_rows == 0


def _table_counts(db: Any) -> tuple[int, int]:
    return (
        int(db.query_df("SELECT COUNT(*) FROM alerts").iloc[0, 0]),
        int(db.query_df("SELECT COUNT(*) FROM nx_account_features").iloc[0, 0]),
    )


def test_ac6_queries_write_no_alerts_and_audit_one_row_each(tiny: Synced, monitored: Any) -> None:
    before = _table_counts(tiny.db)
    calls: list[tuple[str, dict[str, Any]]] = [
        ("cycles", {}),
        ("shared_attributes", {}),
        ("shared_cluster", {"customer": SHR_CUSTOMER}),
        ("fan_in", {}),
        ("fan_out", {}),
    ]
    for name, kw in calls:
        audited = len(graph_audit(tiny.db, "decision = 'QUERIED'"))
        query(tiny.db, tiny.settings, name, **kw)
        after = graph_audit(tiny.db, "decision = 'QUERIED'")
        assert len(after) == audited + 1, name
        assert after.iloc[-1]["entity_id"] == name
    assert _table_counts(tiny.db) == before


def test_ac6_cli_graph_query(tiny_cli: Synced) -> None:
    result = cli("graph", "query", "cycles")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    summary = [ln for ln in lines if "query=cycles" in ln]
    assert len(summary) == 1 and has(summary[0], "rows=2"), lines
    columns = mod("aml.graph.neo4j.queries").QUERY_COLUMNS["cycles"]
    assert any(all(c in ln for c in columns) for ln in lines), lines
    assert any(CYCLE_STEPS in ln for ln in lines), lines

    limited = cli("graph", "query", "shared_cluster", "--customer", SHR_CUSTOMER, "--limit", "3")
    assert limited.exit_code == 0, limited.output
    out = limited.stdout.splitlines()
    head = next(i for i, ln in enumerate(out) if "query=shared_cluster" in ln)
    assert has(out[head], "rows=28")
    assert len(out[head + 2 :]) == 3, out

    fan = cli("graph", "query", "fan_out", "--account", MULE)
    assert fan.exit_code == 0, fan.output
    assert any(has(ln, "rows=1") for ln in fan.stdout.splitlines()), fan.stdout
