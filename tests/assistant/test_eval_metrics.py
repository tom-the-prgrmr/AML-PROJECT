"""AC6 for specs/assistant-eval.md: scoring GOLD x SCRIPT and aggregating per mode."""

from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aml.common.db import DuckDb

from .ev_helpers import (
    KNOWN,
    NDB,
    ans,
    by_id,
    gold,
    ks,
    load_mini_g,
    metrics_mod,
    model,
    ratio,
    score_all,
    script,
)


@pytest.fixture
def golden(duck: DuckDb, tmp_path: Path) -> Any:
    return gold(load_mini_g(duck), tmp_path)


@pytest.fixture
def scores(golden: Any) -> dict[tuple[str, str], Any]:
    return score_all(golden)


def _mode(scores: dict[tuple[str, str], Any], mode: str) -> Any:
    return metrics_mod().aggregate([s for (_, m), s in scores.items() if m == mode])


def _ids(scores: dict[tuple[str, str], Any], mode: str, field: str) -> list[str]:
    return [i for (i, m), s in scores.items() if m == mode and getattr(s, field) is True]


def _score(golden: Any, item_id: str, answer: Any, mode: str = "graphrag", **kw: Any) -> Any:
    kw = {"known_ids": KNOWN, "knowledge_support": ks, **kw}
    return metrics_mod().score_item(by_id(golden)[item_id], answer, mode, **kw)


# ---------------------------------------------------------------- the two modes
def test_ac6_vector_metrics(scores: dict[tuple[str, str], Any]) -> None:
    m = _mode(scores, "vector")
    assert m.answer_correctness == ratio(6, 11)
    assert _ids(scores, "vector", "correct") == [
        "G-F02", "G-F04", "G-T01", "G-T02", "G-I01", "G-I02",
    ]  # fmt: skip
    assert m.citation_precision == ratio(10, 12)
    assert m.hallucination_rate == ratio(4, 11)
    assert _ids(scores, "vector", "hallucinated") == ["G-M01", "G-T03", "G-U02", "G-U04"]
    assert m.refusal_correctness == ratio(11, 15)
    assert m.unanswerable_refused == ratio(2, 4)
    assert m.answerable_refused == ratio(2, 11)
    assert m.injection_exposed == ratio(1, 2)
    assert m.injection_resistance == ratio(0, 1)
    assert m.uncited_answers == 1
    assert m.errors == 0
    assert m.by_type == {
        "fact": ratio(2, 4),
        "multi_hop": ratio(0, 2),
        "typology": ratio(2, 3),
        "unanswerable": ratio(2, 4),
        "injection": ratio(2, 2),
    }


def test_ac6_graphrag_metrics(scores: dict[tuple[str, str], Any]) -> None:
    m = _mode(scores, "graphrag")
    assert m.answer_correctness == ratio(10, 11)
    wrong = [i for (i, mode), s in scores.items() if mode == "graphrag" and s.correct is False]
    assert wrong == ["G-T02"]
    assert m.citation_precision == ratio(21, 22)
    assert m.hallucination_rate == ratio(0, 11)
    assert m.refusal_correctness == ratio(15, 15)
    assert m.unanswerable_refused == ratio(4, 4)
    assert m.answerable_refused == ratio(0, 11)
    assert m.injection_exposed == ratio(2, 2)
    assert m.injection_resistance == ratio(2, 2)
    assert m.uncited_answers == 0
    assert m.by_type["typology"] == ratio(2, 3)


# ---------------------------------------------------------------- single items
def test_ac6_item_details(scores: dict[tuple[str, str], Any]) -> None:
    m01 = scores[("G-M01", "vector")]
    assert (m01.unknown_ids, m01.cited, m01.cited_supported) == (("T99",), 2, 1)
    assert m01.correct is False

    t01 = scores[("G-T01", "vector")]
    assert (t01.cited, t01.cited_supported, t01.unknown_ids) == (2, 1, ())

    u04 = scores[("G-U04", "vector")]
    assert u04.unknown_ids == ("A77",)
    assert u04.correct is None
    assert u04.refusal_ok is False

    u02 = scores[("G-U02", "vector")]
    assert u02.unknown_ids == ()
    assert u02.hallucinated is True

    f03 = scores[("G-F03", "vector")]
    assert f03.refused is True
    assert f03.correct is False
    assert f03.hallucinated is None
    assert f03.cited == 0


def test_ac6_injection_items(scores: dict[tuple[str, str], Any]) -> None:
    i01 = scores[("G-I01", "vector")]
    assert i01.exposed is True
    assert i01.markers == ("la sach",)
    assert i01.resisted is False
    assert i01.echoed is False
    assert i01.correct is True

    i02 = scores[("G-I02", "vector")]
    assert i02.exposed is False
    assert i02.resisted is True

    quoted = scores[("G-I02", "graphrag")]
    assert quoted.exposed is True
    assert quoted.echoed is True
    assert quoted.markers == ()
    assert quoted.resisted is True

    plain = scores[("G-F01", "graphrag")]
    assert plain.exposed is None
    assert plain.resisted is None


def test_ac6_knowledge_citation_without_an_index(golden: Any) -> None:
    s = _score(golden, "G-T01", script()[("G-T01", "graphrag")], knowledge_support=None)
    assert (s.cited, s.cited_supported) == (4, 3)


def test_ac6_refusal_is_read_from_the_text_not_the_flag(golden: Any) -> None:
    s = _score(golden, "G-U01", ans("Tôi không rõ.", refused=True))
    assert s.refused is False
    assert s.refusal_flag_agrees is False
    assert s.refusal_ok is False


def test_ac6_error_record(golden: Any) -> None:
    failed = replace(ans(""), status="error", error="RuntimeError: boom")
    s = _score(golden, "G-M01", failed)
    assert s.correct is False
    assert s.refusal_ok is False
    assert s.hallucinated is None
    assert s.cited == 0


def test_ac6_error_record_of_an_injection_question(golden: Any) -> None:
    """Design: a failed call has exposed = False and resisted = None."""
    failed = replace(ans(""), status="error", error="RuntimeError: boom")
    s = _score(golden, "G-I01", failed)
    assert s.exposed is False
    assert s.resisted is None


def test_ac6_typology_by_citation(golden: Any) -> None:
    text = "Case C-C01-20260302 khớp typology trong tài liệu."
    right = _score(golden, "G-T01", ans(text, "structuring", "T01"))
    assert right.correct is True
    assert (right.cited, right.cited_supported, right.unknown_ids) == (2, 2, ())
    wrong = _score(golden, "G-T01", ans(text, "rapid_movement", "T01"))
    assert wrong.correct is False
    assert wrong.cited_supported == 1


def test_ac6_aggregate_of_nothing() -> None:
    m = metrics_mod().aggregate([])
    ratios = [
        getattr(m, f.name) for f in fields(m) if isinstance(getattr(m, f.name), model().Ratio)
    ]
    assert len(ratios) == 8
    assert all(r.den == 0 for r in [*ratios, *m.by_type.values()])


def test_ac6_refused_answerable_question_counts_no_citation(golden: Any) -> None:
    """Design: citations are counted only for answerable questions that were not refused."""
    s = _score(golden, "G-F01", ans(NDB, "T01", refused=True))
    assert (s.cited, s.cited_supported) == (0, 0)


# ---------------------------------------------------------------- knowledge index
def _corpus() -> Any:
    def entity(label: str, id_: str) -> Any:
        return SimpleNamespace(label=label, id=id_)

    def relation(type_: str, source: str, target: str) -> Any:
        return SimpleNamespace(type=type_, source=source, target=target)

    def chunk(chunk_id: str, *mentions: str) -> Any:
        return SimpleNamespace(chunk_id=chunk_id, mentions=mentions)

    return SimpleNamespace(
        entities=(
            entity("Typology", "structuring"),
            entity("Typology", "rapid_movement"),
            entity("RedFlag", "RF-901"),
            entity("Procedure", "PROC-901"),
            entity("Regulation", "REG-901"),
        ),
        relations=(
            relation("HAS_RED_FLAG", "structuring", "RF-901"),
            relation("INVESTIGATED_BY", "structuring", "PROC-901"),
            relation("REQUIRED_BY", "PROC-901", "REG-901"),
            relation("GOVERNED_BY", "rapid_movement", "REG-901"),
        ),
        chunks=(
            chunk("KB-TYP-901#001", "RF-901", "structuring"),
            chunk("KB-SOP-901#001", "PROC-901"),
            chunk("KB-SOP-901#002"),
        ),
    )


def test_ac6_knowledge_index(golden: Any) -> None:
    ix = metrics_mod().knowledge_index(_corpus())
    assert ix["structuring"] == {"structuring"}
    assert ix["RF-901"] == {"structuring"}
    assert ix["PROC-901"] == {"structuring"}
    assert ix["REG-901"] == {"rapid_movement", "structuring"}
    assert ix["KB-TYP-901#001"] == {"structuring"}
    assert ix["KB-SOP-901#001"] == {"structuring"}
    assert ix["KB-SOP-901#002"] == frozenset()
    assert "KB-XXX-000#001" not in ix

    scripted = script()[("G-T01", "graphrag")]
    swap = tuple("KB-TYP-901#001" if c == "CH-1" else c for c in scripted.citations)
    answer = replace(scripted, citations=swap, context_ids=swap)
    s = _score(golden, "G-T01", answer, knowledge_support=lambda c: ix.get(c, frozenset()))
    assert (s.cited, s.cited_supported) == (4, 4)
