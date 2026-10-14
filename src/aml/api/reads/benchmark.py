"""Benchmark read of the API: the result files of ``aml bench``, exactly as they were written."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from aml.common.config import Settings
from aml.graph.bench.model import BenchCell
from aml.graph.bench.report import NOTES, RESULT_GLOB, path_mismatches, read_results


def _cell(cell: BenchCell) -> dict[str, Any]:
    out = asdict(cell)
    out["runs"] = len(out.pop("seconds"))
    return out


def benchmark(settings: Settings) -> dict[str, Any]:
    """``{runs, notes}``; a corrupt result file raises and becomes the generic internal error."""
    results_dir = settings.path(settings.bench.results_dir)
    names = [p.name for p in sorted(results_dir.glob(RESULT_GLOB))]
    results = read_results(results_dir) if names else []
    runs = [
        {
            "file": name,
            "meta": result.meta,
            "cells": [_cell(c) for c in result.cells],
            "mismatches": path_mismatches(result),
        }
        for name, result in zip(names, results, strict=True)
    ]
    return {"runs": runs, "notes": list(NOTES) if runs else []}
