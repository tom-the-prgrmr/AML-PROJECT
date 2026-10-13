"""AC4 (CLI part) for specs/neo4j-gds.md: `aml graph gds` on TINY after `aml graph sync --full`."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from aml.common.config import get_settings
from aml.common.db import DuckDb
from tests.network.helpers import has

from .helpers import cli, client, neo_settings, set_env

pytestmark = pytest.mark.neo4j


def _runs(path: Path) -> int:
    with DuckDb(path) as db:
        return int(db.query_df("SELECT COUNT(*) FROM gds_runs").iloc[0, 0])


@pytest.fixture(scope="module")
def monkeypatch_module() -> Iterator[pytest.MonkeyPatch]:
    with pytest.MonkeyPatch.context() as mp:
        yield mp
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def synced_cli(
    er_template: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch_module: pytest.MonkeyPatch,
) -> Path:
    """TINY after `aml load` / `aml er` (the template) and `aml graph sync --full`."""
    path = tmp_path_factory.mktemp("gds_cli") / "tiny.duckdb"
    shutil.copy(er_template, path)
    settings = neo_settings()
    driver = client().open_driver(settings)
    try:
        client().run_write_file(driver, settings, "sync/wipe.cypher")
    finally:
        driver.close()
    set_env(monkeypatch_module, {"DB_BACKEND": "duckdb", "AML__DB__DUCKDB_PATH": str(path)})
    result = cli("graph", "sync", "--full")
    assert result.exit_code == 0, result.output
    return path


def test_ac4_cli_bad_date_exits_2_and_writes_nothing(synced_cli: Path) -> None:
    before = _runs(synced_cli)
    result = cli("graph", "gds", "--as-of", "2026-13-01")
    assert result.exit_code == 2, result.output
    assert "No such command" not in result.stderr
    assert _runs(synced_cli) == before


def test_ac4_cli_gds_prints_the_run_and_the_three_graphs(synced_cli: Path) -> None:
    result = cli("graph", "gds")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    summary = [ln for ln in lines if has(ln, "run_id=1")]
    assert len(summary) == 1, lines
    for token in (
        "as_of=2026-06-30",
        "accounts=532",
        "active=298",
        "wcc_components=9",
        "louvain_communities=20",
        "shared_clusters=2",
        "gds=2.13.13",
    ):
        assert has(summary[0], token), (token, summary[0])
    graphs = [ln for ln in lines if "relationships=" in ln]
    assert len(graphs) == 3, lines
    assert "nodes=298 relationships=450" in graphs[0]
    assert "nodes=298 relationships=900" in graphs[1]
    assert "nodes=35 relationships=66" in graphs[2]
    assert _runs(synced_cli) == 1
