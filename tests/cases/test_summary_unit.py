"""AC1 for specs/case-summary.md: config, constants, the Protocol, the registry, `escape_md`.

Nothing here touches a database: the module under test is pure apart from `summarize`.
"""

from __future__ import annotations

import dataclasses

import pytest

from aml.common.config import load_settings
from aml.dba.schema import SCHEMA_SCRIPTS

from .summary_helpers import WATERMARK, mod, narrative, source_of

SECTION_TITLES = (
    "Subject",
    "Alerts",
    "Priority factors",
    "Activity",
    "Network",
    "Data quality",
    "History",
)


def test_ac1_config_defaults_come_from_config_yaml() -> None:
    settings = load_settings(environ={})
    assert settings.cases.summary.generator == "template"
    assert settings.cases.summary.language == "en"


def test_ac1_constants_are_pinned() -> None:
    n = narrative()
    assert n.SUMMARY_VERSION == "summary/v1"
    assert n.TEMPLATE_WATERMARK == WATERMARK
    assert tuple(n.SECTION_TITLES) == SECTION_TITLES


def test_ac1_narrative_is_a_frozen_dataclass_with_the_seven_fields() -> None:
    n = narrative()
    assert dataclasses.is_dataclass(n.Narrative)
    assert [f.name for f in dataclasses.fields(n.Narrative)] == [
        "case_id",
        "markdown",
        "generator",
        "version",
        "language",
        "watermark",
        "citations",
    ]
    item = n.Narrative("C-A-20260101", "m", "g", "v", "en", "m", ())
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.markdown = "other"  # type: ignore[misc]
    assert issubclass(n.NarrativeError, RuntimeError)


def test_ac1_protocol_is_checkable_at_run_time() -> None:
    n = narrative()
    assert isinstance(n.TemplateNarrativeGenerator(), n.NarrativeGenerator)
    assert not isinstance(object(), n.NarrativeGenerator)


def test_ac1_template_generator_is_registered_and_nope_is_not() -> None:
    n = narrative()
    settings = load_settings(environ={})
    template = n.get_generator("template", settings)
    assert template.name == "template"
    assert template.version == "summary/v1"
    with pytest.raises(n.NarrativeError) as err:
        n.get_generator("nope", settings)
    assert "unknown narrative generator 'nope'" in str(err.value)
    assert "template" in str(err.value)  # the list of available names


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        (None, "-"),
        ("", "-"),
        ("  a\n\n b ", "a b"),
        ("x | y", "x \\| y"),
        ("# CLEARED **now**", "\\# CLEARED \\*\\*now\\*\\*"),
        ("a_b [c] <d> `e`", "a\\_b \\[c\\] \\<d\\> \\`e\\`"),
        ("Kế toán", "Kế toán"),
        (1990, "1990"),
        # from the rule of the spec: every whitespace run becomes one space, then the characters
        # of the list get a backslash (the backslash itself is on the list)
        ("   \n\t ", "-"),
        ("a\\b", "a\\\\b"),
        (0, "0"),
        ("line one\r\nline two\tend", "line one line two end"),
    ],
)
def test_ac1_escape_md(raw: object, escaped: str) -> None:
    assert narrative().escape_md(raw) == escaped


def test_ac1_module_source_has_no_network_client() -> None:
    source = source_of("aml.cases.narrative")
    for word in ("ollama", "requests", "httpx", "urllib", "neo4j"):
        assert word not in source, word


def test_ac1_no_new_schema_script() -> None:
    for backend in ("duckdb", "oracle"):
        scripts = SCHEMA_SCRIPTS[backend]
        late = [i for i, s in enumerate(scripts) if s.startswith("ddl/050_")]
        assert late, backend
        # 8d (specs/memo-analysis.md AC1) added script 190, 7b-i (specs/ml-anomaly.md AC1) 200
        # and 7b-ii (specs/screening-ml.md AC1) 210; this still proves 7d added none.
        start = scripts.index("ddl/180_case_prioritization.sql")
        later = ["ddl/190_memo_analysis.sql", "ddl/200_ml_anomaly.sql", "ddl/210_screening_ml.sql"]
        assert list(scripts[start + 1 : min(late)]) == later, backend
    assert mod("aml.cases.narrative") is narrative()  # the module is the one the spec names
