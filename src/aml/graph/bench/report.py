"""Result files and the report built from them: JSON in, Markdown table and SVG chart out.

A run writes ``bench_<profile>_<backend>.json``; the report merges every such file in the results
directory. The report is a pure function of the files, so it can be rebuilt (``--report-only``)
and is identical byte for byte for the same files. It states what was measured, never a verdict.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aml.graph.bench.chart import render_chart
from aml.graph.bench.model import (
    NOTE_APPROXIMATE,
    STATUS_OK,
    BenchCell,
    BenchError,
    BenchResult,
)

__all__ = ["read_results", "render_chart", "render_report", "write_report", "write_result"]

REPORT_NAME = "bench_report.md"
CHART_NAME = "bench_chart.svg"
RESULT_GLOB = "bench_*.json"
HEADER = (
    "| profile | backend | account | T (h) | hops | method | status | paths | median ms | p95 ms "
    "| query lines | note |"
)
RULE = "|---|---|---|---|---|---|---|---|---|---|---|---|"
NOTES = [
    "Time is `TraceResult.seconds`: the query, fetching the answer into a DataFrame and "
    "normalising it (sorting). The freshness check of `neo4j` (`prepare`), the warm-up runs and "
    "the audit row are outside the clock.",
    "p95 is taken by linear interpolation between the two nearest ranks (the NumPy default). With "
    "fewer than 20 timed runs it is close to the slowest run; min, max and every raw time are in "
    "the JSON file.",
    "`cte_edge` is an approximation (daily edges, top-K), so its number of paths cannot be "
    "compared with the exact methods.",
    "Query lines are the non-blank, non-comment lines of the query that ran. For `pgq` they grow "
    "with the number of hops (one GRAPH_TABLE block per hop); for `neo4j` one Cypher file serves "
    "every hop count.",
    "DuckDB runs in-process; Oracle and Neo4j are reached over the network (local Docker ports). "
    "Methods are comparable only within one file: same backend, same data, a graph synced from "
    "that backend.",
    "`skipped`: the method cannot run there (wrong backend, service down, graph out of sync). "
    "`error`: it ran and failed; the reason is in the note.",
    "The account is the heaviest case by time-ordered 2-hop paths when it was picked "
    "automatically, not a typical one.",
]


# ---------------------------------------------------------------------------------- files
def _cell_from_json(raw: dict[str, Any]) -> BenchCell:
    return BenchCell(**{**raw, "seconds": tuple(raw["seconds"])})


def write_result(result: BenchResult, results_dir: Path) -> Path:
    """Write ``bench_<profile>_<backend>.json``; a later run of the same pair overwrites it."""
    meta = result.meta
    path = results_dir / f"bench_{meta['profile']}_{meta['backend']}.json"
    payload = {"meta": meta, "cells": [asdict(c) for c in result.cells]}
    path.write_bytes((json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return path


def read_results(results_dir: Path) -> list[BenchResult]:
    """Every ``bench_*.json`` of the directory, in file-name order."""
    results = []
    for path in sorted(results_dir.glob(RESULT_GLOB)):
        raw = json.loads(path.read_text(encoding="utf-8"))
        results.append(BenchResult(raw["meta"], [_cell_from_json(c) for c in raw["cells"]]))
    return results


# ---------------------------------------------------------------------------------- Markdown
def _text(value: object) -> str:
    return "n/a" if value is None else str(value)


def _md(value: str) -> str:
    """Safe inside a table cell."""
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _ms(value: float | None) -> str:
    return "" if value is None else f"{value:.1f}"


def _count(value: int | None) -> str:
    return "" if value is None else str(value)


def _note(cell: BenchCell) -> str:
    if cell.reason:
        return _md(cell.reason)
    return "" if cell.exact else NOTE_APPROXIMATE


def _row(meta: dict[str, Any], cell: BenchCell) -> str:
    values = [
        meta["profile"],
        meta["backend"],
        cell.account,
        str(cell.hours),
        str(cell.hops),
        cell.method,
        cell.status,
        _count(cell.n_paths) if cell.status == STATUS_OK else "",
        _ms(cell.median_ms),
        _ms(cell.p95_ms),
        _count(cell.query_lines),
        _note(cell),
    ]
    return "| " + " | ".join(values) + " |"


def _provenance(meta: dict[str, Any]) -> list[str]:
    versions, machine = meta["versions"], meta["machine"]
    params, data, sync = meta["params"], meta["dataset"], meta["sync"]
    how = "picked automatically" if params["picked"] else "given in the config"
    lines = [
        f"## {meta['profile']} on {meta['backend']}",
        "",
        f"- Command: `{meta['command']}`, started {meta['started_at']} (UTC), "
        f"{meta['total_seconds']} s in total, commit {_text(meta['git_commit'])}",
        f"- Versions: python {versions['python']}, aml {_text(versions['aml'])}, "
        f"{_text(versions['driver'])}, server {_text(versions['server'])}, "
        f"neo4j driver {_text(versions.get('neo4j_driver'))}",
        f"- Machine: {machine['platform']}, {_text(machine['processor'])}, "
        f"{_text(machine['cpu_count'])} logical CPUs",
        f"- Data: {data['customers']} customers, {data['accounts']} accounts, "
        f"{data['transactions']} transactions, {data['transfers']} transfers",
        f"- Runs: {params['warmup_runs']} warm-up and {params['runs']} timed runs per cell; "
        f"hops {params['hops']}, T {params['hours']} h; accounts {params['accounts']} ({how})",
        f"- Trace limits: max_paths {meta['trace']['max_paths']}, "
        f"cte_edge min amount {meta['trace']['edge_min_amount_vnd']} VND, "
        f"top-K {meta['trace']['edge_top_k']}; Neo4j read timeout {meta['read_timeout_seconds']} s",
    ]
    if sync:
        lines.append(
            f"- Graph sync: FULL {_text(sync['full_seconds'])} s, "
            f"INCREMENTAL {_text(sync['incremental_seconds'])} s, "
            f"lag after the last run {sync['lag_after_seconds']} s"
        )
    return lines


def path_mismatches(result: BenchResult) -> list[str]:
    """One line per (account, T, hops) whose exact methods did not return the same paths.

    `cte_raw`, `pgq` and `neo4j` answer the same question, so their timings are only comparable
    when their path counts agree; a difference means one of them read different data.
    """
    groups: dict[tuple[str, int, int], dict[str, int]] = {}
    for cell in result.cells:
        if cell.status == STATUS_OK and cell.exact and cell.n_paths is not None:
            groups.setdefault((cell.account, cell.hours, cell.hops), {})[cell.method] = cell.n_paths
    lines = []
    for (account, hours, hops), counts in groups.items():
        if len(set(counts.values())) > 1:
            found = ", ".join(f"{method} {n}" for method, n in counts.items())
            lines.append(f"{account}, T {hours} h, {hops} hops: {found}")
    return lines


def render_report(results: Sequence[BenchResult]) -> str:
    """The report as Markdown text: one provenance block and one table per result file."""
    lines = [
        "# Fund-flow trace benchmark",
        "",
        "Built by `aml bench` from the result files (`bench_*.json`) of this directory. "
        "Rebuild it with `aml bench --report-only`.",
        "",
    ]
    if not results:
        lines += ["No result files.", ""]
    for result in results:
        lines += _provenance(result.meta)
        lines += ["", HEADER, RULE]
        lines += [_row(result.meta, cell) for cell in result.cells]
        lines.append("")
        for mismatch in path_mismatches(result):
            lines += [f"**Warning: the exact methods disagree on the paths** ({mismatch}).", ""]
    lines += ["## Notes", ""]
    lines += [f"- {note}" for note in NOTES]
    return "\n".join(lines) + "\n"


def write_report(results_dir: Path) -> tuple[Path, Path]:
    """Write ``bench_report.md`` and ``bench_chart.svg`` from the files of ``results_dir``."""
    results = read_results(results_dir)
    if not results:
        raise BenchError(f"no benchmark results in {results_dir}: run aml bench first")
    report, chart = results_dir / REPORT_NAME, results_dir / CHART_NAME
    report.write_bytes(render_report(results).encode("utf-8"))
    render_chart(results, chart)
    return report, chart
