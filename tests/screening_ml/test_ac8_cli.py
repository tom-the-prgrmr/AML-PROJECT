"""AC8 for specs/screening-ml.md: the `aml screen-ml` command group."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aml.common.config import get_settings
from aml.common.db import DuckDb

from .helpers import RANKING_ONLY_LINE, mod, scalar


def _invoke(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, list(args))


@pytest.fixture
def use_db(
    tiny_env: Callable[..., dict[str, str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[Path], Path]:
    """``use_db(template)`` makes a copy of a TINY database the configured DuckDB."""

    def use(template: Path) -> Path:
        path = tmp_path / "tiny.duckdb"
        shutil.copy(template, path)
        for key, value in tiny_env().items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return path

    return use


def test_ac8_run_prints_the_comparison_and_writes_json(
    use_db: Callable[[Path], Path], tiny_s_path: Path, tmp_path: Path
) -> None:
    path = use_db(tiny_s_path)
    out = tmp_path / "scrml.json"
    result = _invoke("screen-ml", "run", "--fraction", "1.0", "--top", "3", "--eval-out", str(out))
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    labels = [ln for ln in lines if ln.startswith("labels")]
    assert len(labels) == 1
    for token in ("labelled=55", "TRUE_MATCH=5", "FALSE_MATCH=50"):
        assert token in labels[0]
    model = [ln for ln in lines if ln.startswith("model")]
    assert len(model) == 1
    assert "version=scrml/logreg/1" in model[0] and "pairs=55" in model[0]
    assert len([ln for ln in lines if ln.startswith("cv two_tier_alert ")]) == 1
    assert len([ln for ln in lines if ln.startswith("cv two_tier ")]) == 1
    assert not [ln for ln in lines if ln.startswith("holdout")]
    scored = [ln for ln in lines if ln.startswith("scored")]
    assert len(scored) == 1 and "pairs=55" in scored[0]
    ranked = [ln for ln in lines if ln[:2] in ("1 ", "2 ", "3 ")]
    assert [ln[0] for ln in ranked] == ["1", "2", "3"]
    assert all("top=" in ln for ln in ranked)
    assert lines[-1] == RANKING_ONLY_LINE

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert set(payload) == {"model", "cv", "holdout"}
    assert payload["model"]["version"] == "scrml/logreg/1"
    assert len(payload["cv"]) == 2
    assert payload["holdout"] == []

    again = _invoke("screen-ml", "train")
    assert again.exit_code == 0, again.output
    assert "version=scrml/logreg/2" in again.stdout
    with DuckDb(path) as db:
        assert scalar(db, "SELECT COUNT(*) FROM screening_ml_models") == 2


def test_ac8_default_fraction_fails_on_too_few_true_matches(
    use_db: Callable[[Path], Path], tiny_s_path: Path
) -> None:
    use_db(tiny_s_path)
    result = _invoke("screen-ml", "run")
    assert result.exit_code == 1, result.output
    assert any(
        ln.startswith("labels") and "TRUE_MATCH=4" in ln for ln in result.stdout.splitlines()
    )
    assert "not enough labelled pairs" in result.stderr


def test_ac8_bad_fraction_is_a_usage_error(
    use_db: Callable[[Path], Path], tiny_s_path: Path
) -> None:
    use_db(tiny_s_path)
    assert _invoke("screen-ml", "label", "--fraction", "0").exit_code == 2


def test_ac8_existing_commands_still_work() -> None:
    assert _invoke("screen", "--help").exit_code == 0
    assert _invoke("screen-compare", "--help").exit_code == 0


def test_ac8_without_screening_fails_cleanly(
    use_db: Callable[[Path], Path], tiny_loaded_path: Path
) -> None:
    use_db(tiny_loaded_path)
    result = _invoke("screen-ml", "run")
    assert result.exit_code == 1, result.output
    assert "run `aml screen` first" in result.stderr
