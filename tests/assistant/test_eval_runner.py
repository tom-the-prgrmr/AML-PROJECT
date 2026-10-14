"""AC8 for specs/assistant-eval.md: `run_eval` on MINI-G with scripted answers (FN)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aml.common.db import DuckDb

from .ev_helpers import (
    GOLD_IDS,
    MODES,
    Fn,
    count,
    ev_settings,
    eval_audit,
    gold,
    jsonl,
    key,
    ks,
    load_mini_g,
    model,
    names,
    ratio,
    runner_mod,
)

ORDER = [(item_id, mode) for item_id in GOLD_IDS for mode in MODES]
FILES = {"eval_answers.jsonl", "eval_result.json", "eval_report.md", "eval_items.csv"}


@pytest.fixture
def mini(duck: DuckDb) -> DuckDb:
    return load_mini_g(duck)


@pytest.fixture
def golden(mini: DuckDb, tmp_path: Path) -> Any:
    return gold(mini, tmp_path)


def _run(db: DuckDb, golden: Any, fn: Any, out: Path, **kw: Any) -> Any:
    kw = {"key": key(), "knowledge_support": ks, **kw}
    return runner_mod().run_eval(db, ev_settings(out), golden, answer_fn=fn, results_dir=out, **kw)


def _full(db: DuckDb, golden: Any, tmp_path: Path) -> Any:
    """Metrics of a complete run in a directory of its own (the reference)."""
    return _run(db, golden, Fn(), tmp_path / "reference").metrics


# ---------------------------------------------------------------- the first run
def test_ac8_first_run(mini: DuckDb, golden: Any, tmp_path: Path) -> None:
    out, fn = tmp_path / "d", Fn()
    audit_before = count(mini, "audit_log")
    r = _run(mini, golden, fn, out)

    assert fn.calls == ORDER
    assert names(out) == FILES
    lines = jsonl(out / "eval_answers.jsonl")
    assert len(lines) == 30
    for line in lines:
        assert line["golden"] == golden.meta["fingerprint"]
        assert (line["llm_model"], line["embed_model"], line["prompt_version"]) == (
            "m1",
            "e1",
            "p1",
        )
    assert r.metrics["vector"].answer_correctness == ratio(6, 11)
    assert r.metrics["graphrag"].citation_precision == ratio(21, 22)
    assert list(r.metrics) == ["vector", "graphrag"]

    meta = r.meta
    assert meta["schema"] == "rag-eval/v1"
    assert (meta["items_total"], meta["items_answered"], meta["partial"]) == (15, 15, False)
    assert (meta["asked"], meta["reused"], meta["errors"]) == (30, 0, 0)
    assert meta["side_effects"] == {}
    assert (meta["llm_model"], meta["prompt_version"], meta["seed"]) == ("m1", "p1", 42)
    for name in ("command", "started_at", "total_seconds", "git_commit", "versions", "machine"):
        assert name in meta, name
    assert meta["golden"]["fingerprint"] == golden.meta["fingerprint"]
    assert meta["modes"] == ["vector", "graphrag"]
    assert meta["params"] == {"limit": None, "types": None, "force": False}
    assert meta["llm_calls"] == {"chat": 0, "embed": 0}

    assert count(mini, "audit_log") == audit_before + 1
    (row,) = eval_audit(mini)
    assert (row["module"], row["entity_type"], row["decision"], row["version"]) == (
        "assistant",
        "evaluation",
        "EVALUATED",
        "rag-eval/v1",
    )
    assert row["entity_id"] == golden.meta["fingerprint"]
    assert row["reason"] == (
        "assistant evaluation on 15 of 15 questions x 2 modes: 30 asked, 0 reused, 0 failed"
    )
    assert row["details"]["modes"] == ["vector", "graphrag"]
    assert row["details"]["prompt_version"] == "p1"


def test_ac8_rerun_reuses_force_and_new_key_ask_again(
    mini: DuckDb, golden: Any, tmp_path: Path
) -> None:
    out, fn = tmp_path / "d", Fn()
    first = _run(mini, golden, fn, out)

    again = _run(mini, golden, fn, out)
    assert len(fn.calls) == 30
    assert (again.meta["asked"], again.meta["reused"]) == (0, 30)
    assert again.metrics == first.metrics
    assert len(jsonl(out / "eval_answers.jsonl")) == 30

    _run(mini, golden, fn, out, force=True)
    assert len(fn.calls) == 60
    assert len(jsonl(out / "eval_answers.jsonl")) == 60

    _run(mini, golden, fn, out, key=key("m2"))
    assert len(fn.calls) == 90


def test_ac8_partial_run_then_the_rest(mini: DuckDb, golden: Any, tmp_path: Path) -> None:
    out, fn = tmp_path / "d", Fn()
    r = _run(mini, golden, fn, out, types=("fact", "unanswerable"), limit=2)
    assert fn.calls == [(i, m) for i in ("G-F01", "G-F02") for m in MODES]
    assert r.meta["partial"] is True
    assert r.meta["items_answered"] == 2
    assert "2 of 15 questions" in eval_audit(mini)[-1]["reason"]
    assert "PARTIAL RUN: 2 of 15 questions" in (out / "eval_report.md").read_text("utf-8")

    rest = _run(mini, golden, fn, out)
    assert len(fn.calls) == 4 + 26
    assert rest.metrics == _full(mini, golden, tmp_path)


def test_ac8_one_mode_only(mini: DuckDb, golden: Any, tmp_path: Path) -> None:
    fn = Fn()
    r = _run(mini, golden, fn, tmp_path / "d", modes=("graphrag",))
    assert len(fn.calls) == 15
    assert list(r.metrics) == ["graphrag"]


def test_ac8_interrupted_run_resumes(mini: DuckDb, golden: Any, tmp_path: Path) -> None:
    out = tmp_path / "d"

    def stop(n: int, item: Any, mode: str) -> None:
        if n == 8:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run(mini, golden, Fn(stop), out)
    answers = out / "eval_answers.jsonl"
    assert len(jsonl(answers)) == 7

    fn = Fn()
    resumed = _run(mini, golden, fn, out)
    assert len(fn.calls) == 23
    assert resumed.metrics == _full(mini, golden, tmp_path)

    with answers.open("ab") as handle:  # a write that was cut short
        handle.write(b'{"item_id": "G-F0')
    quiet = Fn()
    _run(mini, golden, quiet, out)
    assert quiet.calls == []


def test_ac8_store_survives_line_separators_and_a_torn_multibyte_tail(tmp_path: Path) -> None:
    from aml.assistant.eval.store import append_answer, load_answers

    path = tmp_path / "eval_answers.jsonl"
    texts = {"G-F01": "hello\u2028world", "G-F02": "nel\x85here", "G-F03": "không đủ bằng chứng"}
    for item_id, text in texts.items():
        answer = model().EvalAnswer(text, (), (), False, (), "")
        append_answer(path, "fp", item_id, "vector", key(), answer)
    with path.open("ab") as handle:  # cut short inside the two bytes of "ô"
        handle.write(b'{"item_id": "G-F04", "text": "Kh' + "ô".encode()[:1])

    loaded = load_answers(path, "fp", key())
    assert {item_id: a.text for (item_id, _), a in loaded.items()} == texts

    late = model().EvalAnswer("ok", (), (), False, (), "")
    append_answer(path, "fp", "G-F05", "vector", key(), late)  # starts on a fresh line
    assert set(load_answers(path, "fp", key())) == {(i, "vector") for i in (*texts, "G-F05")}
    assert load_answers(path, "another-golden", key()) == {}


def test_ac8_repeated_mode_is_refused(mini: DuckDb, golden: Any, tmp_path: Path) -> None:
    fn = Fn()
    with pytest.raises(model().EvalError) as err:
        _run(mini, golden, fn, tmp_path / "d", modes=("vector", "vector"))
    assert "modes must not repeat" in str(err.value)
    assert fn.calls == []


def test_ac8_failed_call_is_recorded_and_asked_again(
    mini: DuckDb, golden: Any, tmp_path: Path
) -> None:
    out = tmp_path / "d"

    def boom(n: int, item: Any, mode: str) -> None:
        if (item.id, mode) == ("G-M01", "graphrag"):
            raise RuntimeError("boom")

    fn = Fn(boom)
    r = _run(mini, golden, fn, out)
    assert len(fn.calls) == 30
    assert r.meta["errors"] == 1
    graph = r.metrics["graphrag"]
    assert graph.errors == 1
    assert graph.answer_correctness == ratio(9, 11)
    assert graph.citation_precision == ratio(18, 19)
    assert graph.hallucination_rate == ratio(0, 10)
    assert graph.refusal_correctness == ratio(14, 15)
    record = next(
        line
        for line in jsonl(out / "eval_answers.jsonl")
        if (line["item_id"], line["mode"]) == ("G-M01", "graphrag")
    )
    assert record["status"] == "error"
    assert record["error"] == "RuntimeError: boom"
    assert "1 failed" in eval_audit(mini)[-1]["reason"]

    retry = Fn()
    fixed = _run(mini, golden, retry, out)
    assert retry.calls == [("G-M01", "graphrag")]
    assert fixed.meta["errors"] == 0
    assert fixed.metrics == _full(mini, golden, tmp_path)


def test_ac8_a_write_to_a_decision_table_is_reported(
    mini: DuckDb, golden: Any, tmp_path: Path
) -> None:
    def write(n: int, item: Any, mode: str) -> None:
        if n == 3:
            mini.execute(
                "INSERT INTO case_dispositions (disposition_id, case_id, run_id, disposition, "
                "reason, actor, origin, decided_on, decided_ts) VALUES (1, 'C-C01-20260302', 1, "
                "'FALSE_POSITIVE', 'test', 'tester', 'HUMAN', DATE '2026-06-30', "
                "TIMESTAMP '2026-06-30 00:00:00')"
            )

    out = tmp_path / "d"
    r = _run(mini, golden, Fn(write), out)
    assert r.meta["side_effects"] == {"case_dispositions": 1}
    report = (out / "eval_report.md").read_text("utf-8").splitlines()
    assert "SIDE EFFECTS: case_dispositions +1" in report


def test_ac8_unknown_type_and_mode(mini: DuckDb, golden: Any, tmp_path: Path) -> None:
    fn = Fn()
    with pytest.raises(model().EvalError) as err:
        _run(mini, golden, fn, tmp_path / "d", types=("riddle",))
    assert "unknown question type 'riddle'" in str(err.value)
    with pytest.raises(model().EvalError) as err:
        _run(mini, golden, fn, tmp_path / "d", modes=("hybrid",))
    assert "unknown mode 'hybrid'" in str(err.value)
    assert fn.calls == []


def test_ac8_load_known_ids(mini: DuckDb) -> None:
    asked = {"T01", "T99", "A06", "EXT-02", "G-C01", "C-C01-20260302", "A77", "CH-1"}
    assert runner_mod().load_known_ids(mini, asked) == {
        "T01",
        "A06",
        "EXT-02",
        "G-C01",
        "C-C01-20260302",
    }


def test_ac8_the_run_is_read_only_on_decision_tables(
    mini: DuckDb, golden: Any, tmp_path: Path
) -> None:
    tables = ("case_dispositions", "cases", "case_alerts", "good_guy_list", "alerts")
    before = {t: count(mini, t) for t in tables}
    _run(mini, golden, Fn(), tmp_path / "d")
    assert {t: count(mini, t) for t in tables} == before
