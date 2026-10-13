"""Case narratives: the `NarrativeGenerator` interface, its registry, and `summarize`.

Phase 7 ships one generator, the deterministic template in `summary_template.py`. Phase 8 registers
an LLM-backed one under another name and nothing that calls `summarize` changes. Every generator is
held to the same contract, checked here: it answers for the case it was asked about and its
watermark appears in the text. A generator only ever receives a PII-masked `CaseView`.

`summarize` is a pure read: it writes no table and no audit row, and it never closes, clears or
recommends anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from aml.cases.summary_template import (
    SECTION_TITLES,
    SUMMARY_VERSION,
    TEMPLATE_WATERMARK,
    escape_md,
    render_summary,
)
from aml.cases.view import CaseView, load_case
from aml.common.config import Settings
from aml.common.db import Database

TEMPLATE_LANGUAGE = "en"


class NarrativeError(RuntimeError):
    """An unknown generator or language, or a generator that broke the narrative contract."""


@dataclass(frozen=True)
class Narrative:
    case_id: str
    markdown: str
    generator: str  # registered name, e.g. "template"
    version: str  # template or prompt version, e.g. "summary/v1"
    language: str
    watermark: str  # must appear verbatim in `markdown`
    citations: tuple[str, ...]  # item_key of the alerts the text refers to, in order


@runtime_checkable
class NarrativeGenerator(Protocol):
    name: str
    version: str

    def generate(self, case: CaseView, *, language: str = "en") -> Narrative: ...


class TemplateNarrativeGenerator:
    """The Phase 7 generator: `render_summary`, English only."""

    name = "template"
    version = SUMMARY_VERSION

    def generate(self, case: CaseView, *, language: str = "en") -> Narrative:
        if language != TEMPLATE_LANGUAGE:
            raise NarrativeError(
                f"language '{language}' is not available in the template generator"
            )
        return Narrative(
            case_id=case.case_id,
            markdown=render_summary(case),
            generator=self.name,
            version=self.version,
            language=language,
            watermark=TEMPLATE_WATERMARK,
            citations=tuple(alert.item_key for alert in case.alerts),
        )


GeneratorFactory = Callable[[Settings], NarrativeGenerator]
_REGISTRY: dict[str, GeneratorFactory] = {"template": lambda settings: TemplateNarrativeGenerator()}


def register_generator(name: str, factory: GeneratorFactory) -> None:
    """Make a generator selectable by name (`cases.summary.generator` or `generator=`)."""
    _REGISTRY[name] = factory


def get_generator(name: str, settings: Settings) -> NarrativeGenerator:
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY))
        raise NarrativeError(f"unknown narrative generator '{name}'; available: {available}")
    return _REGISTRY[name](settings)


def _check_contract(narrative: Narrative, case_id: str) -> None:
    problems = []
    if narrative.case_id != case_id:
        problems.append(f"answered for {narrative.case_id!r}, not {case_id!r}")
    if not narrative.markdown:
        problems.append("empty markdown")
    if not narrative.watermark:
        problems.append("empty watermark")
    elif narrative.watermark not in narrative.markdown:
        problems.append("watermark missing from the markdown")
    if problems:
        raise NarrativeError(
            f"narrative contract violated by generator '{narrative.generator}': "
            + "; ".join(problems)
        )


def summarize(
    db: Database,
    settings: Settings,
    case_id: str,
    *,
    generator: str | None = None,
    language: str | None = None,
    run_id: int | None = None,
) -> Narrative:
    """Load the masked case and let the chosen generator describe it.

    `generator` and `language` default to `settings.cases.summary`. Raises `CaseError` for an
    unknown case and `NarrativeError` for an unknown generator or a broken contract.
    """
    config = settings.cases.summary
    chosen = get_generator(generator or config.generator, settings)
    case = load_case(db, case_id, run_id=run_id, masked=True)
    narrative = chosen.generate(case, language=language or config.language)
    _check_contract(narrative, case_id)
    return narrative


def write_summaries(db: Database, settings: Settings, out_dir: Path) -> int:
    """Write `<case_id>.md` (UTF-8) for every case of the current run; return how many."""
    case_ids = db.query_df("SELECT case_id FROM cases_current ORDER BY case_id").iloc[:, 0]
    out_dir.mkdir(parents=True, exist_ok=True)
    for case_id in case_ids:
        text = summarize(db, settings, str(case_id)).markdown
        (out_dir / f"{case_id}.md").write_bytes(as_file_bytes(text))
    return len(case_ids)


def as_file_bytes(markdown: str) -> bytes:
    """UTF-8 with one trailing newline: the same bytes on stdout and in a file."""
    return (markdown + "\n").encode("utf-8")


__all__ = [
    "SECTION_TITLES",
    "SUMMARY_VERSION",
    "TEMPLATE_WATERMARK",
    "Narrative",
    "NarrativeError",
    "NarrativeGenerator",
    "TemplateNarrativeGenerator",
    "as_file_bytes",
    "escape_md",
    "get_generator",
    "register_generator",
    "render_summary",
    "summarize",
    "write_summaries",
]
