"""AC8 for specs/ml-governance.md: every audit row that holds a model's output names the model."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aml.common.audit import audit
from aml.common.config import get_settings
from aml.common.db import DuckDb
from aml.ml.anomaly.runner import run_anomaly
from tests.cases.prio_helpers import PINNED, copy_tiny, make_tiny_l
from tests.memo.helpers import MODEL, Stub
from tests.memo.test_memo_gold import EVAL_REASON, G6, SCRIPT6, write_gold

from .helpers import (
    SAMPLE,
    SIMULATE,
    audit_check,
    audit_df,
    btl_model,
    btl_settings,
    cli,
    mod,
    prio,
    stub_risk,
)

UseStage = Callable[[str], Path]
ELEVEN = [
    ("cases", "PRIORITIZED", None),
    ("cases", "MODEL_TRAINED", None),
    ("cases", "SCORING_RUN_COMPLETED", None),
    ("cases", "BTL_EVALUATED", None),
    ("memo", "MEMO_CLASSIFIED", None),
    ("memo", "MEMO_EVAL_COMPLETED", None),
    ("monitoring", "ALERT", "ML_ANOMALY"),
    ("ml_anomaly", "ANOMALY_RUN_COMPLETED", None),
    ("screening_ml", "MODEL_TRAINED", None),
    ("screening_ml", "ML_SCORED", None),
    ("screening_ml", "ML_SCORING_COMPLETED", None),
]


def _pause() -> None:
    time.sleep(0.05)  # the clock must move between "just before" and the rows written next


def test_ac8_the_eleven_pairs() -> None:
    pairs = [(d.module, d.decision, d.rule_id) for d in audit_check().MODEL_DECISIONS]
    assert pairs == ELEVEN


def test_ac8_the_cases_and_memo_chain(
    cli_db: UseStage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = cli_db("full")
    monkeypatch.setenv(SIMULATE, "false")
    monkeypatch.setenv(SAMPLE, "50")
    for key, value in PINNED.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    settings = get_settings()
    gold = write_gold(tmp_path / "gold.csv", G6)
    with DuckDb(path) as db:
        make_tiny_l(db, settings)
        prio().train(db, settings, actor="analyst01")
        prio().score(db, settings, actor="analyst01")
        btl_model().evaluate_btl(db, settings, actor="analyst01")
        btl_model().train_with_btl(db, settings, actor="analyst01")
        prio().score(db, settings, actor="analyst01")
        mod("aml.memo.runner").classify_memos(db, settings, stub_risk())
        mod("aml.memo.evaluate").run_memo_eval(db, settings, Stub(SCRIPT6), gold_path=gold)
        evaluated = audit_df(db, "decision = 'MEMO_EVAL_COMPLETED'")
        assert evaluated["details"].iloc[0]["model"] == MODEL  # G2: the model is in the details
        assert evaluated["reason"].iloc[0] == EVAL_REASON
        assert audit_check().version_gaps(db) == []

    ok = cli("models", "audit-check")
    assert ok.exit_code == 0, ok.output + ok.stderr
    assert ok.stdout.startswith("audit versions ok:")

    with DuckDb(path) as db:
        _pause()
        since = datetime.now(UTC)
        _pause()
        audit(db, module="cases", entity_type="case", entity_id="C-X", decision="PRIORITIZED",
              reason="no version", version=None)  # fmt: skip
        audit(db, module="cases", entity_type="case", entity_id="C-Y", decision="PRIORITIZED",
              reason="odd version", version="prio/logreg/999")  # fmt: skip
        audit(db, module="memo", entity_type="memo", entity_id="k", decision="MEMO_CLASSIFIED",
              reason="no model", version="memo/v1", details={"category": "other"})  # fmt: skip
        _pause()
        after = datetime.now(UTC)
        gaps = audit_check().version_gaps(db)
        assert [g.problem for g in gaps] == [
            "missing version", "unknown version", "missing details.model",
        ]  # fmt: skip
        assert [(g.module, g.decision, g.entity_id) for g in gaps] == [
            ("cases", "PRIORITIZED", "C-X"),
            ("cases", "PRIORITIZED", "C-Y"),
            ("memo", "MEMO_CLASSIFIED", "k"),
        ]
        assert audit_check().version_gaps(db, since=since) == gaps
        assert audit_check().version_gaps(db, since=after) == []

    bad = cli("models", "audit-check")
    assert bad.exit_code == 1
    lines = bad.stdout.splitlines()
    assert len(lines) == 3
    for line, (module, decision, problem) in zip(
        lines,
        [
            ("cases", "PRIORITIZED", "missing version"),
            ("cases", "PRIORITIZED", "unknown version"),
            ("memo", "MEMO_CLASSIFIED", "missing details.model"),
        ],
        strict=True,
    ):
        assert f"{module}/{decision}" in line and problem in line


def test_ac8_the_anomaly_and_screening_models(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    db = copy_tiny(tiny_stages, tmp_path_factory.mktemp("btl_gaps") / "g.duckdb")
    settings = btl_settings(AML__ML__SCREENING__SIMULATE_FRACTION="1.0")
    try:
        make_tiny_l(db, settings)
        run_anomaly(db, settings)
        labels = mod("aml.screening.ml.labels")
        pipeline = mod("aml.screening.ml.pipeline")
        labels.simulate_labels(db, settings)
        pipeline.train(db, settings)
        pipeline.score(db, settings)
        assert audit_check().version_gaps(db) == []

        audit(db, module="monitoring", entity_type="alert", entity_id="1", decision="ALERT",
              reason="fake", version="ML_ANOMALY/anomaly/v1/999",
              details={"rule_id": "ML_ANOMALY"})  # fmt: skip
        audit(db, module="monitoring", entity_type="alert", entity_id="2", decision="ALERT",
              reason="a rule", version=None, details={"rule_id": "STRUCTURING"})  # fmt: skip
        gaps = audit_check().version_gaps(db)
        assert [(g.module, g.decision, g.problem) for g in gaps] == [
            ("monitoring", "ALERT", "unknown version")
        ]
    finally:
        db.close()
