"""AC9 for specs/screening-ml.md: the model only ranks; nothing it writes is a decision."""

from __future__ import annotations

import inspect
from pathlib import Path

import aml.screening.decision as decision_module
import aml.screening.ml as package
import aml.screening.recording as recording_module

FORBIDDEN = (
    "UPDATE screening_results",
    "INSERT INTO screening_results",
    "record_review",
    "record_disposition",
    "simulate_dispositions",
    "good_guy",
    'decision="TRUE_MATCH"',
    'decision="FALSE_MATCH"',
    'decision="AUTO_CLEARED"',
    'module="screening"',
)


def test_ac9_package_never_decides() -> None:
    files = sorted(Path(package.__file__).parent.glob("*.py"))
    assert {f.name for f in files} >= {"features.py", "labels.py", "model.py", "pipeline.py"}
    for file in files:
        text = file.read_text(encoding="utf-8")
        for needle in FORBIDDEN:
            assert needle not in text, (file.name, needle)


def test_ac9_the_rules_do_not_import_the_model() -> None:
    for module in (decision_module, recording_module):
        assert "aml.screening.ml" not in inspect.getsource(module)
