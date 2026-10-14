"""AC7 for specs/ml-governance.md: model cards generated from stored metadata."""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import aml.cli  # noqa: F401  (imported before the sibling modules are hidden below)
from aml.common.config import get_settings
from aml.common.db import DuckDb
from tests.cases.prio_helpers import PINNED, make_tiny_l

from .helpers import (
    MODEL,
    NEVER_ACTS,
    SAMPLE,
    SIMULATE,
    audit_df,
    btl_model,
    build_tiny_b,
    build_tiny_l,
    cards,
    cli,
    count,
    js,
    mod,
    prio,
    query,
    scalar,
    stub_risk,
)

UseStage = Callable[[str], Path]
HEADINGS = [
    "Intended use", "Human oversight", "Data", "Features", "Metrics", "Limitations", "Audit trail",
]  # fmt: skip


def _facts() -> Any:
    c = cards()
    return c.CardFacts(
        name="prioritization",
        title="Case prioritization",
        version="prio/logreg/1",
        kind="logreg",
        trained="2026-06-30T00:00:00Z",
        seed=42,
        data_hash="0123456789abcdef",
        feature_version="features/v1",
        features=("alerts", "txn_count"),
        source="case_models.model_id=1",
        intended_use="Rank the queue.",
        oversight="A person decides.",
        data=("38 rows",),
        metrics=(("cross-validation", "roc_auc", "0.9"),),
        limitations=("Synthetic.",),
        audit=(c.AuditCoverage("cases", "PRIORITIZED", 52, 52),),
    )


def test_ac7_render_card_is_pure_and_in_order() -> None:
    facts = _facts()
    text = cards().render_card(facts)
    assert text == cards().render_card(facts)
    lines = text.split("\n")
    assert lines[0] == f"# Model card: {facts.title}"
    assert [ln[3:] for ln in lines if ln.startswith("## ")] == HEADINGS
    assert lines[lines.index("## Human oversight") + 1] == NEVER_ACTS
    assert text.endswith("\n") and not text.endswith("\n\n") and "\r" not in text
    assert "| Feature set | features/v1 (2 features) |" in text
    assert "- cases/PRIORITIZED: 52 of 52 row(s) carry version prio/logreg/1" in text
    assert "| Seed | 42 |" in text


@pytest.fixture(scope="module")
def state(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[SimpleNamespace]:
    db, settings = build_tiny_l(tiny_stages, tmp_path_factory)
    prio().train(db, settings, actor="analyst01")
    prio().score(db, settings, actor="analyst01")
    btl_model().evaluate_btl(db, settings, actor="analyst01")
    mod("aml.memo.runner").classify_memos(db, settings, stub_risk())
    model = query(db, "SELECT * FROM case_models WHERE model_id = 1").iloc[0]
    yield SimpleNamespace(db=db, settings=settings, model=model, out=tmp_path_factory.mktemp("c"))
    db.close()


def test_ac7_write_cards_hides_the_siblings_and_writes_two(
    state: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "aml.ml.anomaly.card", None)
    monkeypatch.setitem(sys.modules, "aml.screening.ml.pipeline", None)
    db, settings, out = state.db, state.settings, state.out
    c = cards()
    where = "decision = 'MODEL_CARD_WRITTEN'"
    rep = c.write_cards(db, settings, out_dir=out)
    assert rep.written == (str(out / "prioritization.md"), str(out / "memo_classifier.md"))
    assert rep.skipped == (
        c.Skipped("anomaly", "aml.ml.anomaly.card is not implemented yet (specs/ml-anomaly.md)"),
        c.Skipped(
            "screening_match",
            "aml.screening.ml.pipeline is not implemented yet (specs/screening-ml.md)",
        ),
    )
    first = audit_df(db, where)
    assert list(first["version"]) == ["prio/logreg/1", f"memo/v1 + {MODEL}"]
    for row, name in zip(first.itertuples(), ("prioritization", "memo_classifier"), strict=True):
        data = (out / f"{name}.md").read_bytes()
        assert row.details["sha256"] == hashlib.sha256(data).hexdigest()
        assert row.entity_id == name and row.entity_type == "model_card"

    before = {n: (out / f"{n}.md").read_bytes() for n in ("prioritization", "memo_classifier")}
    again = c.write_cards(db, settings, out_dir=out)
    assert again.written == ()
    assert {n: (out / f"{n}.md").read_bytes() for n in before} == before
    assert len(audit_df(db, where)) == len(first)


def test_ac7_the_prioritization_card_has_the_stored_numbers(state: SimpleNamespace) -> None:
    out = state.out
    cards().write_cards(state.db, state.settings, out_dir=out, names=["prioritization"])
    text = (out / "prioritization.md").read_text(encoding="utf-8")
    model = state.model
    assert "| Version | prio/logreg/1 |" in text
    assert f"| Data hash | {model['data_hash']} |" in text
    assert "| Feature set | features/v1 (35 features) |" in text
    assert str(js(model["metrics"])["roc_auc"]) in text
    assert "| holdout | n | 14 |" in text
    assert "| below-the-line | n | 50 |" in text
    assert "- cases/PRIORITIZED: 52 of 52 row(s) carry version prio/logreg/1" in text
    assert text.endswith("\n") and "\r" not in text


def test_ac7_the_memo_card_says_it_was_not_evaluated(state: SimpleNamespace) -> None:
    cards().write_cards(state.db, state.settings, out_dir=state.out, names=["memo_classifier"])
    text = (state.out / "memo_classifier.md").read_text(encoding="utf-8")
    assert f"| Version | memo/v1 + {MODEL} |" in text
    assert "not evaluated: run `aml memo eval`" in text


def test_ac7_check_lists_a_card_that_differs(state: SimpleNamespace, tmp_path: Path) -> None:
    c = cards()
    db, settings = state.db, state.settings
    names = ["prioritization"]
    c.write_cards(db, settings, out_dir=tmp_path, names=names)
    audit_rows = count(db, "audit_log")
    path = tmp_path / "prioritization.md"
    assert c.write_cards(db, settings, out_dir=tmp_path, names=names, check=True).stale == ()
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("| Seed | 42 |", "| Seed | 43 |"), encoding="utf-8")
    changed = path.read_bytes()
    rep = c.write_cards(db, settings, out_dir=tmp_path, names=names, check=True)
    assert rep.stale == (str(path),) and rep.written == ()
    assert path.read_bytes() == changed
    assert count(db, "audit_log") == audit_rows


def test_ac7_without_models_every_card_is_skipped(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory, tmp_path: Path
) -> None:
    db, settings = build_tiny_b(tiny_stages, tmp_path_factory)
    try:
        rep = cards().write_cards(db, settings, out_dir=tmp_path)
        reasons = {s.name: s.reason for s in rep.skipped}
        assert rep.written == ()
        assert reasons["prioritization"] == "no stored model: run `aml cases train` first"
        assert reasons["memo_classifier"] == "no memo run: run `aml memo classify` first"
        assert not list(tmp_path.iterdir())
    finally:
        db.close()


def test_ac7_the_cli(cli_db: UseStage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = cli_db("full")
    monkeypatch.setenv(SIMULATE, "false")
    monkeypatch.setenv(SAMPLE, "50")
    for key, value in PINNED.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    settings = get_settings()
    with DuckDb(path) as db:
        make_tiny_l(db, settings)
        prio().train(db, settings, actor="analyst01")
    out = tmp_path / "cards"
    result = cli("models", "card", "--out", str(out))
    assert result.exit_code == 0, result.output + result.stderr
    lines = result.stdout.splitlines()
    assert any(ln.startswith("card prioritization -> ") for ln in lines)
    assert any(ln.startswith("skipped anomaly: ") for ln in lines)
    assert (out / "prioritization.md").is_file()
    assert cli("models", "card", "--model", "anomaly", "--out", str(out)).exit_code == 1
    assert cli("models", "card", "--model", "foo").exit_code == 2
    args = ("models", "card", "--model", "prioritization", "--out", str(out), "--check")
    assert cli(*args).exit_code == 0
    card = out / "prioritization.md"
    card.write_text(card.read_text(encoding="utf-8").replace("| Seed | 42 |", "| Seed | 7 |"))
    assert cli(*args).exit_code == 1
    with DuckDb(path) as db:
        written = scalar(db, "SELECT COUNT(*) FROM audit_log WHERE decision = 'MODEL_CARD_WRITTEN'")
        assert written >= 1
