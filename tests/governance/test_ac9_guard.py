"""AC9 for specs/ml-governance.md: no model code path writes a disposition, closes or clears."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from aml.common.config import PROJECT_ROOT

from .helpers import (
    btl,
    btl_model,
    build_tiny_l,
    cards,
    decision_digest,
    guard,
    prio,
)

SRC = PROJECT_ROOT / "src" / "aml"
SCANNED_CASES = (
    "model", "features", "prioritize", "scoring", "prio_store", "btl", "btl_model",
)  # fmt: skip


def test_ac9_the_repository_has_no_violation() -> None:
    assert guard().decision_write_violations() == []


def test_ac9_the_scanned_set() -> None:
    g = guard()
    scanned = {p.relative_to(SRC).as_posix() for pattern in g.SCANNED for p in SRC.glob(pattern)}
    for folder in ("memo", "governance", "ml", "screening/ml"):
        every = {p.relative_to(SRC).as_posix() for p in (SRC / folder).rglob("*.py")}
        assert every and every <= scanned, folder
    for name in SCANNED_CASES:
        assert f"cases/{name}.py" in scanned
    assert "cases/labels.py" not in scanned


def test_ac9_allowed_writers_have_a_reason_and_exist() -> None:
    writers = guard().ALLOWED_WRITERS
    assert "aml.cases.labels" in writers
    for module, reason in writers.items():
        assert reason.strip()
        importlib.import_module(module)


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_ac9_planted_violations_are_found(tmp_path: Path) -> None:
    root = tmp_path / "src" / "aml"
    _write(
        root, "ml/x.py",
        "\nfrom aml.cases.dispositions import record_disposition\n\n__all__ = ['x']\n",
    )  # fmt: skip
    _write(
        root, "memo/y.py", "def run(db):\n    db.execute(\"update cases set status = 'CLOSED'\")\n"
    )
    _write(
        root,
        "governance/z.py",
        'def run(db, frame):\n    db.insert_df("case_dispositions", frame)\n',
    )
    _write(
        root, "screening/ml/w.py",
        "def run(db, audit):\n    audit(db, decision=\"FALSE_POSITIVE\", reason=\"r\")\n",
    )  # fmt: skip
    _write(root, "memo/ok.py", 'SQL = "SELECT case_id FROM case_dispositions_current"\n')
    _write(
        tmp_path, "sql/duckdb/cases/btl_bad.sql", "-- bad\nDELETE FROM case_alerts WHERE 1 = 1;\n"
    )
    found = guard().decision_write_violations(root)
    by_path = {v.path.rsplit("/", 1)[-1]: v for v in found}
    assert len(found) == 5, found
    x = by_path["x.py"]
    assert x.path.endswith("ml/x.py") and x.line == 2 and "record_disposition" in x.what
    assert "UPDATE cases" in by_path["y.py"].what
    assert by_path["z.py"].path.endswith("governance/z.py")
    assert "FALSE_POSITIVE" in by_path["w.py"].what
    assert (
        by_path["btl_bad.sql"].line == 2
        and "DELETE FROM case_alerts" in by_path["btl_bad.sql"].what
    )
    assert "ok.py" not in by_path


@pytest.fixture(scope="module")
def state(
    tiny_stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[SimpleNamespace]:
    db, settings = build_tiny_l(tiny_stages, tmp_path_factory)
    before = decision_digest(db)
    prio().train(db, settings, actor="analyst01")
    btl().draw_sample(db, settings)
    btl_model().evaluate_btl(db, settings)
    btl_model().train_with_btl(db, settings)
    prio().score(db, settings)
    cards().write_cards(db, settings, out_dir=tmp_path_factory.mktemp("guard_cards"))
    yield SimpleNamespace(before=before, after=decision_digest(db))
    db.close()


def test_ac9_the_chain_changes_no_decision_table(state: SimpleNamespace) -> None:
    assert state.before == state.after
