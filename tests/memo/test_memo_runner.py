"""AC3 for specs/memo-analysis.md: `plan_memos`, `classify_memos`, resume, fallback, guards."""

from __future__ import annotations

import json

import pytest

from aml.common.db import DuckDb
from tests.cases.helpers import count, query

from .helpers import (
    K_CRY,
    K_GAM,
    K_INJ,
    K_LOAN,
    K_SAL,
    MODEL,
    SCRIPT,
    VERSION,
    Stub,
    classify,
    current,
    key_of,
    memo_audit,
    memo_error,
    memoc,
    runner_mod,
    sent,
)

RUN_REASON = (
    "classified 5 new memo key(s) of 5 (1 by rule, 4 by qwen2.5:3b-instruct, 0 fallback), "
    "reused 0; 4 LLM call(s) for 7 transactions with a memo; features only, no alert"
)


def test_ac3_plan_then_two_runs_then_a_new_memo(duck: DuckDb) -> None:
    settings = memoc(duck)
    r = runner_mod()
    stub = Stub(SCRIPT)

    plan = r.plan_memos(duck, settings)
    assert plan == r.MemoPlan(
        transactions=8, with_memo=7, distinct_memos=7, keys=5, reused=0, rule_keys=1, llm_keys=4
    )
    assert count(duck, "memo_runs") == count(duck, "memo_classifications") == 0
    assert len(memo_audit(duck)) == 0

    r1 = classify(duck, settings, stub)
    assert (r1.run_id, r1.version, r1.model) == (1, "memo/v1", MODEL)
    assert (r1.transactions, r1.with_memo, r1.distinct_memos, r1.keys) == (8, 7, 7, 5)
    assert (r1.reused, r1.by_rule, r1.by_llm, r1.fallback, r1.llm_calls, r1.left) == (
        0, 1, 4, 0, 4, 0,
    )  # fmt: skip
    assert len(stub.calls) == 4
    assert sent(stub) == [K_SAL, K_CRY, K_GAM, K_LOAN]  # ascending memo_norm

    rows = current(duck)
    assert {(n, x.category, x.method, int(x.transactions)) for n, x in rows.items()} == {
        (K_LOAN, "loan_repayment", "LLM", 2),
        (K_SAL, "salary", "LLM", 2),
        (K_CRY, "crypto_like", "LLM", 1),
        (K_GAM, "gambling_like", "LLM", 1),
        (K_INJ, "suspicious_wording", "RULE", 1),
    }
    for norm, row in rows.items():
        assert (row.memo_version, row.llm_model, int(row.run_id)) == (VERSION, MODEL, 1)
        assert row.memo_key == key_of(norm)
    categories = r.read_categories(duck, settings)
    assert len(categories) == 5 and categories[key_of(K_INJ)] == "suspicious_wording"

    runs = query(duck, "SELECT * FROM memo_runs")
    assert len(runs) == 1
    assert (int(runs["memo_keys"][0]), int(runs["llm_calls"][0]), int(runs["keys_left"][0])) == (
        5, 4, 0,
    )  # fmt: skip
    assert float(runs["seconds"][0]) >= 0

    classified = memo_audit(duck, "decision = 'MEMO_CLASSIFIED'")
    assert len(classified) == 5
    assert set(classified["entity_type"]) == {"memo"} and set(classified["version"]) == {VERSION}
    by_key = {r_.entity_id: r_.details for r_ in classified.itertuples()}
    inj = by_key[key_of(K_INJ)]
    assert (inj["method"], inj["pattern"], inj["attempts"]) == ("RULE", 1, 0)
    sal = by_key[key_of(K_SAL)]
    assert (sal["category"], sal["model"], sal["transactions"]) == ("salary", MODEL, 2)
    done = memo_audit(duck, "decision = 'MEMO_RUN_COMPLETED'")
    assert len(done) == 1
    assert (done["entity_type"][0], done["entity_id"][0]) == ("memo_run", "1")
    assert done["reason"][0] == RUN_REASON
    everything = memo_audit(duck)
    text = " ".join(
        f"{row.reason} {json.dumps(row.details, ensure_ascii=False)}"
        for row in everything.itertuples()
    ).lower()
    for memo_text in ("ignore previous", "usdt", "bet#"):
        assert memo_text not in text  # no memo text in reason or details

    before = len(everything)
    r2 = classify(duck, settings, stub)
    assert (r2.run_id, r2.reused, r2.by_rule, r2.by_llm, r2.llm_calls, r2.left) == (
        2,
        5,
        0,
        0,
        0,
        0,
    )
    assert len(stub.calls) == 4
    assert count(duck, "memo_classifications") == 5
    after = memo_audit(duck)
    assert len(after) == before + 1
    last = after.iloc[-1]
    assert (last["decision"], last["entity_id"]) == ("MEMO_RUN_COMPLETED", "2")

    duck.execute("UPDATE transactions SET memo = 'Tiền cước internet' WHERE txn_id = 'T01'")
    r3 = classify(duck, settings, stub)
    assert (r3.keys, r3.reused, r3.by_llm, r3.llm_calls) == (6, 5, 1, 1)
    assert current(duck)["tiền cước internet"].category == "other"


def test_ac3_without_an_llm_the_rule_keys_are_stored_and_the_run_resumes(duck: DuckDb) -> None:
    settings = memoc(duck)
    with pytest.raises(memo_error(), match=r"4 memo key\(s\) need the LLM but it is not available"):
        classify(duck, settings, None)
    rows = query(duck, "SELECT method FROM memo_classifications")
    assert list(rows["method"]) == ["RULE"]
    runs = query(duck, "SELECT by_rule, keys_left FROM memo_runs")
    assert len(runs) == 1
    assert (int(runs["by_rule"][0]), int(runs["keys_left"][0])) == (1, 4)
    assert len(memo_audit(duck, "decision = 'MEMO_RUN_INCOMPLETE'")) == 1
    assert len(memo_audit(duck, "decision = 'MEMO_RUN_COMPLETED'")) == 0

    r2 = classify(duck, settings, Stub(SCRIPT))
    assert (r2.run_id, r2.reused, r2.by_llm, r2.left) == (2, 1, 4, 0)


def test_ac3_a_failing_llm_call_keeps_what_was_done(duck: DuckDb) -> None:
    settings = memoc(duck)
    with pytest.raises(memo_error(), match=r"llm call failed after 2 of 4 memo key\(s\)"):
        classify(duck, settings, Stub(SCRIPT, fail_at=3))
    methods = sorted(query(duck, "SELECT method FROM memo_classifications")["method"])
    assert methods == ["LLM", "LLM", "RULE"]
    runs = query(duck, "SELECT keys_left FROM memo_runs")
    assert [int(v) for v in runs["keys_left"]] == [2]

    r2 = classify(duck, settings, Stub(SCRIPT))
    assert (r2.reused, r2.by_llm, r2.llm_calls, r2.left) == (3, 2, 2, 0)


def test_ac3_a_fallback_key_is_asked_again_and_its_old_row_stays(duck: DuckDb) -> None:
    settings = memoc(duck)
    r1 = classify(duck, settings, Stub(SCRIPT, raw={K_GAM: "not json"}))
    assert (r1.by_llm, r1.fallback, r1.llm_calls) == (3, 1, 5)
    gam = current(duck)[K_GAM]
    assert (gam.category, gam.method, int(gam.attempts)) == ("other", "FALLBACK", 2)

    r2 = classify(duck, settings, Stub(SCRIPT))
    assert (r2.reused, r2.by_llm, r2.fallback) == (4, 1, 0)
    assert current(duck)[K_GAM].category == "gambling_like"
    assert count(duck, "memo_classifications") == 6
    assert count(duck, "memo_classifications", "WHERE method = 'FALLBACK'") == 1


def test_ac3_a_client_of_another_model_is_refused_before_any_write(duck: DuckDb) -> None:
    settings = memoc(duck)
    message = "llm client model 'fake-chat' differs from ollama.llm_model 'qwen2.5:3b-instruct'"
    with pytest.raises(memo_error()) as caught:
        classify(duck, settings, Stub(SCRIPT, chat_model="fake-chat"))
    assert message in str(caught.value)
    assert count(duck, "memo_classifications") == count(duck, "memo_runs") == 0
    assert len(memo_audit(duck)) == 0


def test_ac3_more_llm_keys_than_the_limit_stops_before_any_write(duck: DuckDb) -> None:
    settings = memoc(duck, AML__MEMO__MAX_LLM_KEYS="3")
    with pytest.raises(memo_error()) as caught:
        classify(duck, settings, Stub(SCRIPT))
    assert "4 memo keys need the LLM, more than memo.max_llm_keys=3" in str(caught.value)
    assert count(duck, "memo_classifications") == count(duck, "memo_runs") == 0
    assert len(memo_audit(duck)) == 0


def test_ac3_review_an_interrupted_run_is_recorded_and_the_next_run_gets_a_fresh_id(
    duck: DuckDb,
) -> None:
    """AC3 (review fix): Ctrl-C mid-run keeps the done keys, records `left`, re-raises; a run
    killed before its run row was written never makes the next run reuse its id."""
    settings = memoc(duck)
    stub = Stub(SCRIPT, raw={K_GAM: "not json"}, fail_at=5, error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        classify(duck, settings, stub)  # K_SAL, K_CRY, K_GAM (2 calls, FALLBACK), then K_LOAN
    runs = query(duck, "SELECT run_id, keys_left, llm_calls FROM memo_runs")
    assert [(int(r.run_id), int(r.keys_left), int(r.llm_calls)) for r in runs.itertuples()] == [
        (1, 1, 5)
    ]  # the interrupted call is counted
    assert len(memo_audit(duck, "decision = 'MEMO_RUN_INCOMPLETE'")) == 1
    assert current(duck)[K_GAM].method == "FALLBACK"

    duck.execute("DELETE FROM memo_runs")  # as if the process had been killed before that row
    r2 = classify(duck, settings, Stub(SCRIPT))
    assert r2.run_id == 2 and r2.left == 0
    assert (r2.reused, r2.by_llm, r2.fallback) == (3, 2, 0)  # K_GAM is asked again
    assert current(duck)[K_GAM].category == "gambling_like"
    ids = query(duck, "SELECT DISTINCT run_id FROM memo_classifications ORDER BY run_id")
    assert [int(v) for v in ids["run_id"]] == [1, 2]


def test_ac3_review_a_failing_call_is_counted_in_llm_calls(duck: DuckDb) -> None:
    settings = memoc(duck)
    with pytest.raises(memo_error()):
        classify(duck, settings, Stub(SCRIPT, fail_at=3))
    runs = query(duck, "SELECT llm_calls FROM memo_runs")
    assert [int(v) for v in runs["llm_calls"]] == [3]  # two keys done plus the call that failed
