"""AC11 for specs/memo-analysis.md: the gold set file, the few-shot examples and `run_memo_eval`."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path

import pytest

from aml.common.config import PROJECT_ROOT
from aml.common.db import DuckDb
from tests.cases.helpers import count, duck_settings, mod

from .helpers import (
    MODEL,
    SCRIPT,
    Stub,
    classify_mod,
    evaluate_mod,
    memo_audit,
    memo_error,
    normalize_mod,
)

GOLD = PROJECT_ROOT / "docs" / "eval" / "memo_gold_v1.csv"
G6 = [
    ("Lương tháng 05/2026", "salary", "generator"),
    ("Trả nợ vay bạn bè", "loan_repayment", "generator"),
    ("mua USDT qua P2P", "crypto_like", "handwritten"),
    ("Nap tien BET88 keo 3", "gambling_like", "handwritten"),
    ("Tiền điện nước tháng này", "other", "generator"),
    ("Gửi tiền tiết kiệm", "other", "generator"),
]
SCRIPT6 = SCRIPT | {"gửi tiền tiết kiệm": "suspicious_wording"}
EVAL_REASON = (
    "evaluated memo/v1 with qwen2.5:3b-instruct on 6 gold memo(s): 5 correct (accuracy 0.8333); "
    "measurement only, no label stored"
)
ONE = {"n": 1, "correct": 1, "predicted": 1, "precision": 1.0, "recall": 1.0}


def write_gold(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["memo", "category", "source"])
        writer.writerows(rows)
    return path


def test_ac11_repo_gold_file_and_few_shot_examples() -> None:
    n, c, e = normalize_mod(), classify_mod(), evaluate_mod()
    memos = mod("aml.datagen.memos")
    assert duck_settings().memo.gold_path == "docs/eval/memo_gold_v1.csv"
    rows = e.read_gold(GOLD)
    assert len(rows) == 46
    assert Counter(r.category for r in rows) == {
        "other": 17,
        "salary": 4,
        "loan_repayment": 4,
        "gambling_like": 9,
        "crypto_like": 9,
        "suspicious_wording": 3,
    }
    assert Counter(r.source for r in rows) == {"generator": 28, "handwritten": 18}
    keys = {n.normalize_memo(r.memo): r.category for r in rows}
    assert len(keys) == 46  # pairwise different after normalisation
    assert all(n.injection_pattern(k) == 0 for k in keys)
    for templates, category in (
        (memos.GAMBLING_MEMOS, "gambling_like"),
        (memos.CRYPTO_MEMOS, "crypto_like"),
    ):
        for template in templates:
            assert keys[n.normalize_memo(template.format(ref=1))] == category, template

    assert len(c.FEW_SHOT) == 11
    assert {category for _, category in c.FEW_SHOT} == set(c.CATEGORIES)
    generator = {
        n.normalize_memo(t.format(ref=12345))
        for t in [t for _, ts in memos._MEMOS.values() for t in ts]
        + memos.GAMBLING_MEMOS
        + memos.CRYPTO_MEMOS
    }
    for memo, _ in c.FEW_SHOT:
        assert f"- {memo} -> " in c.SYSTEM_PROMPT
        assert n.normalize_memo(memo) == memo
        assert memo not in keys  # the gold set never repeats a few-shot example
        assert memo not in generator
        assert n.injection_pattern(memo) == 0


def test_ac11_run_memo_eval_on_g6(duck: DuckDb, tmp_path: Path) -> None:
    mod("aml.dba.schema").apply_schema(duck)
    settings = duck_settings()
    e = evaluate_mod()
    path = write_gold(tmp_path / "g6.csv", G6)
    stub = Stub(SCRIPT6)

    r = e.run_memo_eval(duck, settings, stub, gold_path=path)
    assert (r["n"], r["correct"], r["accuracy"]) == (6, 5, 0.8333)
    assert (r["version"], r["model"]) == ("memo/v1", MODEL)
    assert r["gold"]["rows"] == 6
    assert r["gold"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    by_category = r["by_category"]
    assert set(by_category) == set(classify_mod().CATEGORIES)
    assert by_category["other"] == {
        "n": 2, "correct": 1, "predicted": 1, "precision": 1.0, "recall": 0.5,
    }  # fmt: skip
    assert by_category["suspicious_wording"] == {
        "n": 0, "correct": 0, "predicted": 1, "precision": 0.0, "recall": None,
    }  # fmt: skip
    for name in ("salary", "loan_repayment", "gambling_like", "crypto_like"):
        assert by_category[name] == ONE, name
    assert r["by_source"] == {
        "generator": {"n": 4, "correct": 3, "accuracy": 0.75},
        "handwritten": {"n": 2, "correct": 2, "accuracy": 1.0},
    }
    assert r["by_method"] == {"RULE": 0, "LLM": 6, "FALLBACK": 0}
    assert r["confusion"]["other"] == {"other": 1, "suspicious_wording": 1}
    assert r["confusion"]["salary"] == {"salary": 1}
    assert r["errors"] == [
        {
            "memo": "Gửi tiền tiết kiệm",
            "expected": "other",
            "predicted": "suspicious_wording",
            "method": "LLM",
        }
    ]
    assert len(stub.calls) == 6
    for table in ("memo_classifications", "memo_runs", "case_memo_features", "memo_overrides"):
        assert count(duck, table) == 0, table
    audit = memo_audit(duck)
    assert len(audit) == 1
    row = audit.iloc[0]
    assert (row["decision"], row["entity_type"]) == ("MEMO_EVAL_COMPLETED", "memo_eval")
    assert row["entity_id"] == r["gold"]["sha256"][:16]
    assert row["reason"] == EVAL_REASON

    # the pure function gives the same numbers from the same rows and predictions
    rows = e.read_gold(path)
    n, c = normalize_mod(), classify_mod()
    predicted = [c.classify_one(n.normalize_memo(g.memo), Stub(SCRIPT6), model=MODEL) for g in rows]
    direct = e.evaluate_gold(rows, predicted)
    for key in ("n", "correct", "accuracy", "by_category", "by_source", "confusion", "errors"):
        assert direct[key] == r[key], key

    low = e.run_memo_eval(duck, settings, Stub({}), gold_path=path)  # no threshold: never raises
    assert (low["correct"], low["accuracy"]) == (2, 0.3333)

    audited = len(memo_audit(duck))
    with pytest.raises(memo_error(), match="need the LLM but it is not available"):
        e.run_memo_eval(duck, settings, None, gold_path=path)
    assert len(memo_audit(duck)) == audited


def test_ac11_read_gold_rejects_a_bad_file(tmp_path: Path) -> None:
    read = evaluate_mod().read_gold
    bad = list(G6)
    bad[1] = ("Trả nợ vay bạn bè", "clean", "generator")
    with pytest.raises(memo_error(), match="unknown category 'clean' in gold row 2"):
        read(write_gold(tmp_path / "bad.csv", bad))
    dup = [*G6, ("  trả  nợ vay bạn bè", "loan_repayment", "handwritten")]
    with pytest.raises(memo_error(), match="duplicate gold memo in row 7"):
        read(write_gold(tmp_path / "dup.csv", dup))
    shot = [*G6, ("Mua BTC", "crypto_like", "handwritten")]
    with pytest.raises(memo_error(), match="gold row 7 is also a few-shot example"):
        read(write_gold(tmp_path / "shot.csv", shot))
    src = [*G6, ("Tiền sinh nhật mẹ", "other", "investigator")]
    with pytest.raises(memo_error()):
        read(write_gold(tmp_path / "src.csv", src))
    assert len(read(write_gold(tmp_path / "ok.csv", G6))) == 6
