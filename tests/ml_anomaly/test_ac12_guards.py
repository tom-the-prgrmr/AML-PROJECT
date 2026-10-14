"""AC12 for specs/ml-anomaly.md: the model only signals; it never closes or clears anything."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from aml.common.db import DuckDb
from tests.cases.helpers import count, duck_settings, js, query
from tests.cases.prio_helpers import copy_tiny, make_tiny_l, table_digest

from .helpers import run_anomaly

ML_ROOT = Path(__file__).resolve().parents[2] / "src" / "aml" / "ml"
ANOMALY_ROOT = ML_ROOT / "anomaly"
GUARDED = (
    "case_dispositions",
    "cases",
    "case_alerts",
    "case_scores",
    "case_models",
    "good_guy_list",
)
FORBIDDEN_TEXT = ("record_disposition", "case_dispositions", "good_guy", "UPDATE ", "DELETE ")


def _digest(db: DuckDb) -> dict[str, object]:
    out: dict[str, object] = {t: count(db, t) for t in GUARDED}
    out["cases_current"] = table_digest(db, "cases_current", "case_id")
    out["dispositions"] = table_digest(db, "case_dispositions", "disposition_id")
    return out


@pytest.fixture(scope="module")
def state(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[SimpleNamespace]:
    db = copy_tiny(tiny_stages, tmp_path_factory.mktemp("anomaly_guard") / "guard.duckdb")
    settings = duck_settings()
    make_tiny_l(db, settings)
    first = run_anomaly(db, settings)
    before = _digest(db)
    second = run_anomaly(db, settings)
    yield SimpleNamespace(db=db, first=first, second=second, before=before, after=_digest(db))
    db.close()


def test_ac12_a_second_run_changes_no_case_table(state: SimpleNamespace) -> None:
    assert state.second.run_id == state.first.run_id + 1
    assert state.before == state.after


def test_ac12_no_forbidden_word_under_src_aml_ml() -> None:
    files = sorted(ML_ROOT.rglob("*.py"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        for word in FORBIDDEN_TEXT:
            assert word not in text, f"{path.name} contains {word!r}"


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_ac12_imports_are_confined() -> None:
    for path in sorted(ANOMALY_ROOT.glob("*.py")):
        imports = _imports(path)
        for banned in ("aml.api", "fastapi", "neo4j"):
            assert not any(i == banned or i.startswith(banned + ".") for i in imports), (
                path.name,
                banned,
            )
        uses_sklearn = any(i == "sklearn" or i.startswith("sklearn.") for i in imports)
        assert uses_sklearn == (path.name == "model.py"), path.name


def test_ac12_anomaly_items_never_hibernate() -> None:
    from aml.cases.hibernation import _HIBERNATING_SOURCES

    assert _HIBERNATING_SOURCES == ("RULE", "NETWORK")


def test_ac12_every_audit_row_and_score_carries_the_model_version(state: SimpleNamespace) -> None:
    db = state.db
    own = query(db, "SELECT version FROM audit_log WHERE module = 'ml_anomaly'")
    assert len(own) == 2
    assert all(re.fullmatch(r"anomaly/v1/\d+", v) for v in own["version"])
    alerts = query(db, "SELECT version, details FROM audit_log WHERE decision = 'ALERT'")
    mine = alerts[[js(d).get("rule_id") == "ML_ANOMALY" for d in alerts["details"]]]
    assert len(mine) == state.first.alerts + state.second.alerts
    assert all(re.fullmatch(r"ML_ANOMALY/anomaly/v1/\d+", v) for v in mine["version"])
    scores = query(
        db,
        "SELECT s.model_version AS scored, r.model_version AS run_version "
        "FROM anomaly_scores s JOIN anomaly_runs r ON r.run_id = s.run_id",
    )
    assert len(scores) == 2 * 1334
    assert (scores["scored"] == scores["run_version"]).all()
    assert all(re.fullmatch(r"anomaly/v1/\d+", v) for v in scores["scored"].unique())
