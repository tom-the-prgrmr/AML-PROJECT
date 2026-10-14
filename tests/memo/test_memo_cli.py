"""AC8 for specs/memo-analysis.md: `aml memo classify|compare|eval` on TINY with Ollama switched
off (`AML__OLLAMA__HOST` points at a closed port), so no test here needs a model."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from aml.common.config import get_settings
from aml.common.db import DuckDb
from tests.cases.helpers import cli, count, has
from tests.cases.prio_helpers import make_tiny_l

from .helpers import Stub, classify, risk_script

UseStage = Callable[[str], Path]
LAST_CLASSIFY = (
    "memo categories are ranking features only: no alert was raised and no case was changed"
)


def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **extra: str) -> None:
    """Point Ollama at a closed port and every output directory at the test's own folder."""
    env = {
        "AML__OLLAMA__HOST": "http://127.0.0.1:1",
        "AML__MEMO__RESULTS_DIR": str(tmp_path / "results"),
        "AML__ASSISTANT__CACHE__DIR": str(tmp_path / "llm_cache"),
        **extra,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def starting(output: str, word: str) -> list[str]:
    return [ln for ln in output.splitlines() if ln.split(" ")[0].split("=")[0] == word]


def test_ac8_classify_dry_run_offline_and_reuse(
    cli_db: UseStage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = cli_db("load")
    offline(monkeypatch, tmp_path)

    dry = cli("memo", "classify", "--dry-run")
    assert dry.exit_code == 0, dry.output
    lines = dry.stdout.splitlines()
    plan = [ln for ln in lines if has(ln, "transactions=5100")]
    assert len(plan) == 1
    for token in (
        "with_memo=3152",
        "distinct_memos=1136",
        "keys=41",
        "reused=0",
        "rule=6",
        "llm=35",
    ):
        assert has(plan[0], token), token
    assert lines[-1] == "dry run: nothing was classified or stored"
    with DuckDb(path) as db:
        assert count(db, "memo_runs") == count(db, "memo_classifications") == 0

    down = cli("memo", "classify")
    assert down.exit_code == 1, down.output
    assert "35 memo key(s) need the LLM but it is not available" in down.stderr
    with DuckDb(path) as db:
        assert count(db, "memo_classifications") == 6
        where = "WHERE method = 'RULE' AND category = 'suspicious_wording'"
        assert count(db, "memo_classifications", where) == 6
        assert count(db, "memo_runs") == 1
        assert count(db, "memo_runs", "WHERE keys_left = 35") == 1
        classify(db, get_settings(), Stub(risk_script()))  # the model's part, by a function call

    done = cli("memo", "classify")  # Ollama is still off: nothing is left to ask
    assert done.exit_code == 0, done.output + done.stderr
    lines = done.stdout.splitlines()
    run = [ln for ln in lines if ln.startswith("run_id=")]
    assert len(run) == 1
    for token in ("keys=41", "reused=41", "rule=0", "llm=0", "llm_calls=0"):
        assert has(run[0], token), token
    assert [ln for ln in lines if ln.startswith("category=")] == [
        "category=salary keys=0 transactions=0",
        "category=loan_repayment keys=0 transactions=0",
        "category=gambling_like keys=5 transactions=10",
        "category=crypto_like keys=3 transactions=10",
        "category=suspicious_wording keys=6 transactions=6",
        "category=other keys=27 transactions=3126",
    ]
    assert lines.count("methods rule=6 llm=35 human=0 fallback=0") == 1
    assert lines[-1] == LAST_CLASSIFY

    with DuckDb(path) as db:
        audited = count(db, "audit_log")
    ev = cli("memo", "eval")
    assert ev.exit_code == 1, ev.output
    assert "ollama not available" in ev.stderr
    with DuckDb(path) as db:
        assert count(db, "audit_log") == audited

    no_cases = cli("memo", "compare")
    assert no_cases.exit_code == 1, no_cases.output
    assert "run `aml cases build` first" in no_cases.stderr
    assert cli("memo", "compare", "--model", "xgboost").exit_code == 2


def test_ac8_help_lists_the_memo_commands() -> None:
    top = cli("--help")
    assert top.exit_code == 0 and "memo" in top.stdout
    sub = cli("memo", "--help")
    assert sub.exit_code == 0
    for name in ("classify", "compare", "eval", "list", "relabel"):
        assert name in sub.stdout, name


def test_ac8_classify_refuses_more_llm_keys_than_the_limit(
    cli_db: UseStage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = cli_db("load")
    offline(monkeypatch, tmp_path, AML__MEMO__MAX_LLM_KEYS="5")
    result = cli("memo", "classify")
    assert result.exit_code == 1, result.output
    assert "more than memo.max_llm_keys=5" in result.stderr
    with DuckDb(path) as db:
        assert count(db, "memo_classifications") == 0


def test_ac8_compare_on_tiny_l(
    cli_db: UseStage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = cli_db("full")
    offline(monkeypatch, tmp_path)
    with DuckDb(path) as db:
        make_tiny_l(db, get_settings())
        classify(db, get_settings(), Stub(risk_script()))
    out = tmp_path / "memo.json"

    result = cli("memo", "compare", "--eval-out", str(out))
    assert result.exit_code == 0, result.output + result.stderr
    lines = result.stdout.splitlines()
    base = starting(result.stdout, "base")
    assert len(base) == 1 and has(base[0], "features=35") and "prevalence=0.7105" in base[0]
    assert len(starting(result.stdout, "with_memo")) == 1
    delta = starting(result.stdout, "delta")
    assert len(delta) == 1 and "cv_roc_auc=" in delta[0]
    memo = starting(result.stdout, "memo")
    assert len(memo) == 1 and "cases_with_memo=" in memo[0] and "dropped=" in memo[0]
    assert lines[-1] == "measurement only: no model was stored"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert set(payload) == {"memo", "data", "base", "with_memo", "delta", "population"}
    assert payload["data"]["cases"] == 38


def test_ac8_score_without_memo_labels_behaves_as_in_7c(cli_db: UseStage) -> None:
    cli_db("sources")
    result = cli("score")
    assert result.exit_code == 1, result.output
    assert "not enough labelled cases" in result.stderr
