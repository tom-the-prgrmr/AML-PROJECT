"""AC1 for specs/assistant-eval.md: config, constants, module hygiene and the document."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from aml.common.config import PROJECT_ROOT, load_settings

from .ev_helpers import model, text_mod

EVAL_DIR = PROJECT_ROOT / "src" / "aml" / "assistant" / "eval"
PURE_MODULES = ("golden", "text", "metrics", "store", "report", "runner", "model")
FORBIDDEN = (
    "ollama",
    "neo4j",
    "httpx",
    "requests",
    "urllib",
    "aml.assistant.llm",
    "aml.assistant.retriev",
    "aml.assistant.answer",
)


def test_ac1_defaults_from_config_yaml() -> None:
    cfg = load_settings(environ={}).rag_eval
    assert cfg.questions == {
        "fact": 8,
        "multi_hop": 8,
        "typology": 6,
        "unanswerable": 4,
        "injection": 4,
    }
    assert sum(cfg.questions.values()) == 30
    assert cfg.english_per_type == 1
    assert cfg.modes == ["vector", "graphrag"]
    assert cfg.results_dir == "results/phase8"


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        (
            "QUESTIONS",
            "{fact: -1, multi_hop: 0, typology: 0, unanswerable: 0, injection: 0}",
            "questions must be >= 0",
        ),
        ("QUESTIONS", "{fact: 1}", "questions must have exactly the keys"),
        (
            "QUESTIONS",
            "{fact: 0, multi_hop: 0, typology: 0, unanswerable: 0, injection: 0}",
            "questions must ask at least one question",
        ),
        ("MODES", "[]", "modes must not be empty"),
        ("MODES", "[vector, hybrid]", "unknown mode 'hybrid'"),
        ("ENGLISH_PER_TYPE", "-1", "english_per_type must be >= 0"),
    ],
)
def test_ac1_invalid_config_is_rejected(name: str, value: str, message: str) -> None:
    with pytest.raises(ValidationError) as err:
        load_settings(environ={f"AML__RAG_EVAL__{name}": value})
    assert message in str(err.value)


def test_ac1_repeated_mode_is_rejected() -> None:
    """The interface says modes hold no repeats (not listed in AC1, same rule)."""
    with pytest.raises(ValidationError):
        load_settings(environ={"AML__RAG_EVAL__MODES": "[vector, vector]"})


def test_ac1_constants() -> None:
    m = model()
    assert m.GOLDEN_SCHEMA == "golden/v1"
    assert m.EVAL_SCHEMA == "rag-eval/v1"
    assert m.TYPES == ("fact", "multi_hop", "typology", "unanswerable", "injection")
    assert m.MODES == ("graphrag", "vector")
    assert text_mod().REFUSAL_PHRASES == ("không đủ bằng chứng", "insufficient evidence")


def test_ac1_ratio_value() -> None:
    m = model()
    assert m.Ratio(6, 11).value == pytest.approx(0.545454, abs=1e-6)
    assert m.Ratio(0, 0).value is None


@pytest.mark.parametrize("name", PURE_MODULES)
def test_ac1_engine_modules_do_not_reach_services_or_8abc(name: str) -> None:
    source = (EVAL_DIR / f"{name}.py").read_text(encoding="utf-8")
    assert [word for word in FORBIDDEN if word in source] == []


def test_ac1_document_exists_and_names_the_essentials() -> None:
    doc: Path = PROJECT_ROOT / "docs" / "assistant-eval.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for needle in (
        "aml rag eval",
        "--limit",
        "--report-only",
        "answer correctness",
        "citation precision",
        "hallucination rate",
        "refusal correctness",
        "injection resistance",
        "golden_set.json",
    ):
        assert needle in text, needle
