"""AC9 for specs/memo-analysis.md: the real path through Ollama and the on-disk cache of 8a.

Nothing here asserts how good the model is: the labels only have to stay inside the closed set,
the rule layer has to win for known injection text, and a rebuilt database has to get the same
labels back from the cache.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aml.common.config import load_settings, read_environ
from aml.common.db import DuckDb
from tests.cases.helpers import count, load_minic, mod, query

from .helpers import (
    K_INJ,
    classify,
    classify_mod,
    effective,
    evaluate_mod,
    normalize_mod,
    set_memos,
)


def _labels(db: DuckDb) -> set[tuple[str, str, str]]:
    df = query(db, "SELECT memo_key, category, method FROM memo_classifications_current")
    return set(zip(df["memo_key"], df["category"], df["method"], strict=True))


@pytest.mark.ollama
def test_ac9_real_model_stays_in_the_closed_set_and_the_cache_repeats_it(
    duck: DuckDb, tmp_path: Path
) -> None:
    settings = load_settings(
        environ={
            **read_environ(),
            "DB_BACKEND": "duckdb",
            "AML__ASSISTANT__PROVIDER": "ollama",
            "AML__ASSISTANT__CACHE__ENABLED": "true",
            "AML__ASSISTANT__CACHE__DIR": str(tmp_path / "llm_cache"),
        }
    )
    model = settings.ollama.llm_model
    c, n = classify_mod(), normalize_mod()
    client = mod("aml.assistant.llm").get_llm(settings)
    load_minic(duck)
    set_memos(duck)

    r1 = classify(duck, settings, client)
    assert (r1.keys, r1.by_rule, r1.left) == (5, 1, 0)
    assert r1.by_llm + r1.fallback == 4
    assert 4 <= r1.llm_calls <= 8
    assert r1.seconds > 0
    assert set(query(duck, "SELECT category FROM memo_classifications")["category"]) <= set(
        c.CATEGORIES
    )
    assert effective(duck, K_INJ) == ("suspicious_wording", "RULE")
    first = _labels(duck)

    r2 = classify(duck, settings, client)
    assert r2.reused == r1.by_rule + r1.by_llm
    assert r2.llm_calls <= 2 * r1.fallback
    assert r2.by_llm + r2.fallback == r1.fallback

    for phrase in mod("aml.datagen.memos").INJECTION_PHRASES:  # the rule layer switched off
        got = c.classify_one(
            n.normalize_memo("Chuyển khoản. " + phrase), client, model=model, use_rules=False
        )
        assert got.category in c.CATEGORIES and got.method in ("LLM", "FALLBACK"), phrase

    with DuckDb(tmp_path / "rebuilt.duckdb") as rebuilt:  # same cache directory, empty tables
        load_minic(rebuilt)
        set_memos(rebuilt)
        classify(rebuilt, settings, client)
        assert _labels(rebuilt) == first

    e = evaluate_mod()
    before = count(duck, "memo_classifications")
    measured = e.run_memo_eval(duck, settings, client)  # the gold set of the repository
    assert measured["n"] == 46
    assert measured["by_method"]["RULE"] == 0
    assert 0 <= measured["correct"] <= 46
    assert measured["accuracy"] == round(measured["correct"] / 46, 4)
    cells = [v for row in measured["confusion"].values() for v in row.values()]
    assert sum(cells) == 46
    predicted = {label for row in measured["confusion"].values() for label in row}
    assert predicted <= set(c.CATEGORIES)
    assert count(duck, "memo_classifications") == before
    again = e.run_memo_eval(duck, settings, client)  # same cache: the same answers
    for key in ("correct", "confusion", "errors"):
        assert again[key] == measured[key], key
