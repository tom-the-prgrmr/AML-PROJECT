"""AC12 for specs/memo-analysis.md: a person relabels a memo key (`relabel_memo`, `aml memo list`,
`aml memo relabel`); the model's label stays, the person's label wins, nothing else changes."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path

import pytest

from aml.common.config import get_settings
from aml.common.db import DuckDb
from tests.cases.helpers import CASE_C01_A, cli, count, query, run_cases

from .helpers import (
    K_INJ,
    K_LOAN,
    K_SAL,
    SCRIPT,
    Stub,
    classify,
    current,
    effective,
    features_mod,
    key_of,
    memo_audit,
    memo_error,
    memoc,
    relabel_mod,
    risk_script,
    runner_mod,
)
from .test_memo_cli import offline

UseStage = Callable[[str], Path]
UNTOUCHED = ("cases", "case_alerts", "case_dispositions", "alerts", "case_scores", "case_models")
LAST_RELABEL = (
    "label changed by a person: no alert was raised and no case was changed; "
    "features follow at the next aml score"
)


def test_ac12_relabel_memo_keeps_the_model_label_and_wins_in_features(duck: DuckDb) -> None:
    settings = memoc(duck)
    rl, f = relabel_mod(), features_mod()
    run_cases(duck, settings)
    classify(duck, settings, Stub(SCRIPT))
    assert f.write_memo_features(duck, settings, 1) == 30
    before = {t: count(duck, t) for t in UNTOUCHED}

    r = rl.relabel_memo(
        duck, settings, key_of(K_LOAN), "suspicious_wording",
        reason="borrower is a known mule collector", actor="analyst01",
    )  # fmt: skip
    assert r == rl.Relabel(
        override_id=1,
        memo_key=key_of(K_LOAN),
        category="suspicious_wording",
        previous_category="loan_repayment",
        previous_method="LLM",
        actor="analyst01",
    )
    assert rl.labels_rev(duck) == 1
    assert count(duck, "memo_classifications") == 5
    loan = current(duck)[K_LOAN]
    assert (loan.category, loan.method) == ("loan_repayment", "LLM")  # the model's answer stays
    assert count(duck, "memo_overrides") == 1

    labels = rl.list_labels(duck, settings)
    assert len(labels) == 5
    assert list(labels["memo_norm"]) == sorted(labels["memo_norm"])
    rows = {
        x.memo_norm: (x.category, x.method, int(x.transactions), x.model_category, x.model_method)
        for x in labels.itertuples()
    }
    assert rows[K_LOAN] == ("suspicious_wording", "HUMAN", 2, "loan_repayment", "LLM")
    assert rows[K_SAL] == ("salary", "LLM", 2, "salary", "LLM")
    assert len(rl.list_labels(duck, settings, method="HUMAN")) == 1
    assert len(rl.list_labels(duck, settings, method="LLM")) == 3
    assert len(rl.list_labels(duck, settings, method="RULE")) == 1
    assert len(rl.list_labels(duck, settings, category="suspicious_wording")) == 2
    assert len(rl.list_labels(duck, settings, category="loan_repayment")) == 0
    assert runner_mod().read_categories(duck, settings)[key_of(K_LOAN)] == "suspicious_wording"

    assert (
        f.read_memo_features(duck, settings, 1) is None
    )  # the labels_rev = 0 rows are not current
    assert {t: count(duck, t) for t in UNTOUCHED} == before
    assert f.write_memo_features(duck, settings, 1) == 30
    assert count(duck, "case_memo_features") == 60
    assert count(duck, "case_memo_features", "WHERE labels_rev = 0") == 30
    assert count(duck, "case_memo_features", "WHERE labels_rev = 1") == 30
    row = f.read_memo_features(duck, settings, 1).loc[CASE_C01_A]
    assert {k: float(v) for k, v in row.items()} == {
        "memo_txns": 4.0,
        "memo_salary": 1.0,
        "memo_loan_repayment": 0.0,
        "memo_gambling_like": 0.0,
        "memo_crypto_like": 1.0,
        "memo_suspicious_wording": 2.0,  # T05 by RULE and T02 confirmed by a person
    }

    again = classify(duck, settings, Stub({}))  # a later run never overwrites a person's label
    assert (again.reused, again.by_llm, again.llm_calls) == (5, 0, 0)
    assert count(duck, "memo_overrides") == 1
    assert effective(duck, K_LOAN) == ("suspicious_wording", "HUMAN")

    first = query(duck, "SELECT * FROM memo_overrides WHERE override_id = 1").iloc[0].to_dict()
    r2 = rl.relabel_memo(
        duck, settings, key_of(K_LOAN), "loan_repayment",
        reason="checked the loan contract", actor="analyst02",
    )  # fmt: skip
    assert (r2.override_id, r2.previous_category, r2.previous_method) == (
        2, "suspicious_wording", "HUMAN",
    )  # fmt: skip
    assert effective(duck, K_LOAN) == ("loan_repayment", "HUMAN")
    assert count(duck, "memo_overrides") == 2
    assert (
        query(duck, "SELECT * FROM memo_overrides WHERE override_id = 1").iloc[0].to_dict() == first
    )

    r3 = rl.relabel_memo(
        duck, settings, key_of(K_SAL)[:8], "salary", reason="confirmed payroll", actor="analyst01"
    )  # an 8-character prefix, confirming the label the model gave
    assert (r3.override_id, r3.memo_key) == (3, key_of(K_SAL))
    assert (r3.previous_category, r3.previous_method) == ("salary", "LLM")

    r4 = rl.relabel_memo(
        duck, settings, key_of(K_INJ), "other",
        reason="test memo typed by the bank's own red team", actor="analyst01",
    )  # fmt: skip
    assert (r4.previous_category, r4.previous_method) == ("suspicious_wording", "RULE")
    assert effective(duck, K_INJ) == ("other", "HUMAN")

    audit = memo_audit(duck, "decision = 'MEMO_RELABELLED'")
    assert len(audit) == 4
    assert set(audit["entity_type"]) == {"memo"} and set(audit["version"]) == {"memo/v1"}
    head = audit.iloc[0]
    assert (head["entity_id"], head["actor"]) == (key_of(K_LOAN), "analyst01")
    assert head["reason"] == "borrower is a known mule collector"
    assert head["details"] == {
        "override_id": 1,
        "category": "suspicious_wording",
        "previous_category": "loan_repayment",
        "previous_method": "LLM",
        "model_category": "loan_repayment",
        "model_method": "LLM",
    }

    written = (count(duck, "memo_overrides"), count(duck, "audit_log"))
    key = key_of(K_LOAN)
    for kwargs, error, message in (
        ({"key": key, "category": "clean"}, memo_error(), "unknown category 'clean'"),
        ({"key": "0" * 32}, memo_error(), "unknown memo key"),
        ({"key": "abc"}, memo_error(), "memo key prefix must be at least 8 characters"),
        ({"key": key, "reason": "  "}, ValueError, ""),
        ({"key": key, "actor": "system"}, memo_error(), "a relabel needs a human actor"),
    ):
        call = {"category": "other", "reason": "x", "actor": "analyst01"} | kwargs
        with pytest.raises(error) as caught:
            rl.relabel_memo(duck, settings, call.pop("key"), call.pop("category"), **call)
        assert message in str(caught.value)
        if error is ValueError:
            assert not isinstance(caught.value, memo_error())
    assert (count(duck, "memo_overrides"), count(duck, "audit_log")) == written
    assert {t: count(duck, t) for t in UNTOUCHED} == before

    source = inspect.getsource(rl)
    for word in ("record_disposition", "record_run", "INSERT INTO alerts"):
        assert word not in source


def _key_lines(output: str) -> list[str]:
    return output.splitlines()[:-1]


def test_ac12_cli_list_and_relabel(
    cli_db: UseStage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = cli_db("load")
    offline(monkeypatch, tmp_path)
    with DuckDb(path) as db:
        classify(db, get_settings(), Stub(risk_script()))
    key = key_of("trả nợ vay bạn bè")

    listed = cli("memo", "list")
    assert listed.exit_code == 0, listed.output
    assert len(_key_lines(listed.stdout)) == 41
    assert listed.stdout.splitlines()[-1] == "41 memo key(s)"
    for args, last in (
        (("--method", "RULE"), "6 memo key(s)"),
        (("--category", "gambling_like"), "5 memo key(s)"),
        (("--method", "HUMAN"), "0 memo key(s)"),
    ):
        result = cli("memo", "list", *args)
        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[-1] == last, args

    done = cli(
        "memo", "relabel", key, "loan_repayment",
        "--reason", "repayment of a personal loan", "--actor", "analyst01",
    )  # fmt: skip
    assert done.exit_code == 0, done.output + done.stderr
    lines = done.stdout.splitlines()
    head = [ln for ln in lines if "override_id=1" in ln]
    assert len(head) == 1
    for token in ("category=loan_repayment", "previous=other/LLM", "actor=analyst01"):
        assert token in head[0], token
    assert lines[-1] == LAST_RELABEL

    again = cli("memo", "classify")  # Ollama is still off
    assert again.exit_code == 0, again.output + again.stderr
    lines = again.stdout.splitlines()
    assert "reused=41" in again.stdout and "llm_calls=0" in again.stdout
    assert "category=loan_repayment keys=1 transactions=293" in lines
    assert "category=other keys=26 transactions=2833" in lines
    assert "methods rule=6 llm=34 human=1 fallback=0" in lines
    human = cli("memo", "list", "--method", "HUMAN")
    rows = _key_lines(human.stdout)
    assert len(rows) == 1
    for token in ("loan_repayment HUMAN", "transactions=293", "model=other/LLM"):
        assert token in rows[0], token

    tail = ("--reason", "x", "--actor", "analyst01")
    assert cli("memo", "relabel", key, "clean", *tail).exit_code == 2
    assert cli("memo", "relabel", key, "other", "--actor", "analyst01").exit_code == 2
    assert cli("memo", "relabel", key, "other", "--reason", "x").exit_code == 2
    unknown = cli("memo", "relabel", "00000000", "other", *tail)
    assert unknown.exit_code == 1 and "unknown memo key" in unknown.stderr
    system = cli("memo", "relabel", key, "other", "--reason", "x", "--actor", "system")
    assert system.exit_code == 1 and "a relabel needs a human actor" in system.stderr
    assert cli("memo", "list", "--method", "BAD").exit_code == 2
    with DuckDb(path) as db:
        assert count(db, "memo_overrides") == 1
