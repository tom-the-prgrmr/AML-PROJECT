"""AC4 and AC9 for specs/assistant-eval.md: `aml rag eval` on TINY (DuckDB, no service).

TINY here is `aml load` + `aml er` (2 structuring, 2 rapid_movement, 2 round_tripping, 1 mule_ring,
6 prompt_injection), without `aml cases build`.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import get_settings, load_settings
from aml.common.db import DuckDb
from tests.network.conftest import er_template, tiny_env, tiny_parquet  # noqa: F401 (fixtures)

from .ev_helpers import (
    MODES,
    NDB,
    ans,
    cli,
    count,
    golden_mod,
    key,
    names,
    ratio,
    runner_mod,
)

QUESTIONS = "{fact: 4, multi_hop: 3, typology: 0, unanswerable: 4, injection: 4}"
GOLDEN_LINE = (
    "golden items=15 fact=4 multi_hop=3 typology=0 unanswerable=4 injection=4 fingerprint="
)
ADAPTER = "aml.assistant.eval.adapter"


@pytest.fixture
def tiny(
    er_template: Path,  # noqa: F811
    tiny_env: Any,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """TINY + ER as the configured DuckDB; returns the env, the database path, the results dir."""
    db_path = tmp_path / "tiny.duckdb"
    shutil.copy(er_template, db_path)
    out = tmp_path / "eval"
    env = {
        **tiny_env(),
        "AML__RAG_EVAL__QUESTIONS": QUESTIONS,
        "AML__RAG_EVAL__RESULTS_DIR": str(out),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    return {"env": env, "db": db_path, "out": out}


def _values(db: DuckDb, sql: str) -> set[str]:
    return {str(v) for v in db.query_df(sql).iloc[:, 0] if v is not None}


# ---------------------------------------------------------------- AC4
def test_ac4_golden_only_is_repeatable_and_read_only(tiny: dict[str, Any]) -> None:
    out: Path = tiny["out"]
    with DuckDb(tiny["db"]) as db:
        audit_before = count(db, "audit_log")
    contents = []
    for _ in range(2):
        done = cli("rag", "eval", "--golden-only")
        assert done.exit_code == 0, done.output
        lines = done.stdout.splitlines()
        assert len([ln for ln in lines if ln.startswith(GOLDEN_LINE)]) == 1, lines
        assert len([ln for ln in lines if ln.startswith("wrote")]) == 1, lines
        assert names(out) == {"golden_set.json"}
        contents.append((out / "golden_set.json").read_bytes())
    assert contents[0] == contents[1]
    with DuckDb(tiny["db"]) as db:
        assert count(db, "audit_log") == audit_before


def test_ac4_golden_items_match_the_database(tiny: dict[str, Any]) -> None:
    assert cli("rag", "eval", "--golden-only").exit_code == 0
    golden = golden_mod().read_golden(tiny["out"])
    items = {i.id: i for i in golden.items}

    multi_hop = [i.template for i in golden.items if i.type == "multi_hop"]
    assert multi_hop == ["hop_round_trip", "hop_pass_through", "hop_mule_collector"]
    assert all(i.case_id is None for i in golden.items)

    with DuckDb(tiny["db"]) as db:
        known = (
            _values(db, "SELECT txn_id FROM transactions")
            | _values(db, "SELECT from_account_id FROM transactions")
            | _values(db, "SELECT to_account_id FROM transactions")
            | _values(db, "SELECT account_id FROM accounts")
            | _values(db, "SELECT golden_customer_id FROM customer_golden")
        )
        amounts = {
            str(r.txn_id): int(r.amount_vnd)
            for r in db.query_df("SELECT txn_id, amount_vnd FROM transactions").itertuples()
        }
        memos = {
            str(r.txn_id): str(r.memo)
            for r in db.query_df(
                "SELECT t.txn_id, t.memo FROM transactions t JOIN ground_truth g "
                "ON g.entity_id = t.txn_id WHERE g.typology = 'prompt_injection'"
            ).itertuples()
        }
        cases = _values(db, "SELECT case_id FROM cases")

    for item in golden.items:
        if item.type == "unanswerable":
            continue
        assert item.expected_ids or item.expected_values, item.id
        assert set(item.expected_ids) <= known, item.id
        assert set(item.evidence_ids) <= known, item.id
        if item.expected_values:
            (txn,) = re.findall(r"T\d{10}", item.question)
            assert item.expected_values == (amounts[txn],), item.id

    for item_id, pattern in (("G-U01", r"A\d{10}"), ("G-U02", r"T\d{10}")):
        (missing,) = re.findall(pattern, items[item_id].question)
        assert missing not in known
    (case,) = re.findall(r"C-CIF\d{8}-\d{8}", items["G-U04"].question)
    assert case not in cases

    injection = [i for i in golden.items if i.type == "injection"]
    asked = [re.findall(r"T\d{10}", i.question)[0] for i in injection]
    assert len(set(asked)) == 4
    for item, txn in zip(injection, asked, strict=True):
        assert txn in memos, item.id
        assert item.injection_phrase
        assert memos[txn].endswith(item.injection_phrase)


def test_ac4_help_lists_the_six_flags(tiny: dict[str, Any]) -> None:
    done = cli("rag", "eval", "--help")
    assert done.exit_code == 0, done.output
    for flag in ("--golden-only", "--report-only", "--limit", "--type", "--mode", "--force"):
        assert flag in done.stdout, flag


# ---------------------------------------------------------------- AC9
def _refuse_everything(item: Any, mode: str) -> Any:
    return ans(NDB)


def test_ac9_refusing_everything_is_scored_and_reported(tiny: dict[str, Any]) -> None:
    out: Path = tiny["out"]
    assert cli("rag", "eval", "--golden-only").exit_code == 0
    golden = golden_mod().read_golden(out)
    assert len(golden.items) == 15
    tables = ("case_dispositions", "cases", "alerts")
    with DuckDb(tiny["db"]) as db:
        before = {t: count(db, t) for t in tables}
        r = runner_mod().run_eval(
            db,
            load_settings(environ=tiny["env"]),
            golden,
            answer_fn=_refuse_everything,
            key=key(),
            results_dir=out,
        )
    assert list(r.metrics) == list(MODES)
    for mode in MODES:
        m = r.metrics[mode]
        assert m.answer_correctness == ratio(0, 11)
        assert m.citation_precision == ratio(0, 0)
        assert m.hallucination_rate == ratio(0, 0)
        assert m.refusal_correctness == ratio(4, 15)
        assert m.unanswerable_refused == ratio(4, 4)
        assert m.answerable_refused == ratio(11, 11)
        assert m.injection_exposed == ratio(0, 4)
        assert m.injection_resistance == ratio(0, 0)

    done = cli("rag", "eval", "--report-only")
    assert done.exit_code == 0, done.output
    report = (out / "eval_report.md").read_text(encoding="utf-8").splitlines()
    for line in (
        "| answer correctness | 0/11 (0.0%) | 0/11 (0.0%) |",
        "| citation precision | n/a | n/a |",
        "| hallucination rate | n/a | n/a |",
        "| refusal correctness | 4/15 (26.7%) | 4/15 (26.7%) |",
        "| injection resistance | n/a | n/a |",
        "| injection exposed | 0/4 | 0/4 |",
    ):
        assert report.count(line) == 1, line
    with DuckDb(tiny["db"]) as db:
        assert {t: count(db, t) for t in tables} == before


@pytest.mark.parametrize(
    "args", [("--type", "riddle"), ("--mode", "hybrid"), ("--limit", "0")], ids=lambda a: a[0]
)
def test_ac9_invalid_arguments_exit_2(tiny: dict[str, Any], args: tuple[str, str]) -> None:
    done = cli("rag", "eval", *args)
    assert done.exit_code == 2, done.output
    assert names(tiny["out"]) == set()  # rejected before anything is read or written


@pytest.mark.parametrize("changed", ["seed", "dataset"])
def test_ac9_golden_set_of_another_dataset_is_refused(tiny: dict[str, Any], changed: str) -> None:
    assert cli("rag", "eval", "--golden-only").exit_code == 0
    path: Path = tiny["out"] / "golden_set.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if changed == "seed":
        raw["meta"]["seed"] = 7
    else:
        raw["meta"]["dataset"]["transactions"] += 1
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    done = cli("rag", "eval")
    assert done.exit_code == 1, done.output
    assert "golden set was built for another dataset" in done.stderr
    assert names(tiny["out"]) == {"golden_set.json"}


def test_ac9_aml_help_still_lists_rag(tiny: dict[str, Any]) -> None:
    done = cli("--help")
    assert done.exit_code == 0, done.output
    assert "rag" in done.stdout
    group = cli("rag", "--help")
    for command in ("build", "status", "eval"):
        assert command in group.stdout, command


# ---------------------------------------------------------------- until the adapter exists
@pytest.mark.skipif(
    importlib.util.find_spec(ADAPTER) is not None,
    reason="the adapter exists: the full run is covered by AC10",
)
def test_full_run_without_the_adapter_fails_cleanly(tiny: dict[str, Any]) -> None:
    """Not an AC: while `adapter.py` (8b / 8c) is missing, the full run says so and asks nothing."""
    with DuckDb(tiny["db"]) as db:
        audit_before = count(db, "audit_log")
    done = cli("rag", "eval", "--limit", "1")
    assert done.exit_code == 1, done.output
    assert ADAPTER in done.stderr
    assert "Traceback" not in done.stderr
    assert names(tiny["out"]) == {"golden_set.json"}  # built and written first, as specified
    with DuckDb(tiny["db"]) as db:
        assert count(db, "audit_log") == audit_before
