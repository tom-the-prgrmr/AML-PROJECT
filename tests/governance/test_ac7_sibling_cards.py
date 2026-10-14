"""Cards of the two sibling models (specs/ml-anomaly.md, specs/screening-ml.md), read from what
they stored; the spec's AC7 only needs them skipped, this checks the adapters against the real
modules."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from aml.ml.anomaly.runner import run_anomaly
from tests.cases.prio_helpers import copy_tiny, make_tiny_l

from .helpers import btl_settings, cards, mod


@pytest.fixture(scope="module")
def state(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[SimpleNamespace]:
    db = copy_tiny(tiny_stages, tmp_path_factory.mktemp("btl_sib") / "s.duckdb")
    settings = btl_settings(AML__ML__SCREENING__SIMULATE_FRACTION="1.0")
    make_tiny_l(db, settings)
    anomaly = run_anomaly(db, settings)
    mod("aml.screening.ml.labels").simulate_labels(db, settings)
    pipeline = mod("aml.screening.ml.pipeline")
    trained = pipeline.train(db, settings)
    pipeline.score(db, settings)
    out = tmp_path_factory.mktemp("sib_cards")
    report = cards().write_cards(db, settings, out_dir=out, names=["anomaly", "screening_match"])
    yield SimpleNamespace(db=db, anomaly=anomaly, trained=trained, out=out, report=report)
    db.close()


def test_sibling_cards_are_written(state: SimpleNamespace) -> None:
    assert state.report.skipped == ()
    assert state.report.written == (
        str(state.out / "anomaly.md"),
        str(state.out / "screening_match.md"),
    )


def test_anomaly_card_names_the_run_and_its_alert_rows(state: SimpleNamespace) -> None:
    text = (state.out / "anomaly.md").read_text(encoding="utf-8")
    version = state.anomaly.model_version
    assert f"| Version | {version} |" in text
    assert re.search(
        rf"- monitoring/ALERT: (\d+) of \1 row\(s\) carry version ML_ANOMALY/{version}", text
    )
    assert f"- ml_anomaly/ANOMALY_RUN_COMPLETED: 1 of 1 row(s) carry version {version}" in text
    assert "This model never closes, clears, files or dispositions anything." in text


def test_screening_card_names_the_model_and_its_audit_rows(state: SimpleNamespace) -> None:
    text = (state.out / "screening_match.md").read_text(encoding="utf-8")
    version = state.trained.version
    assert f"| Version | {version} |" in text
    assert re.search(
        rf"- screening_ml/ML_SCORED: (\d+) of \1 row\(s\) carry version {version}", text
    )
    assert f"- screening_ml/MODEL_TRAINED: 1 of 1 row(s) carry version {version}" in text
    assert "| held-out |" in text
