"""SVG chart of the benchmark: median time against hops, one panel per (result file, account).

Every setting that could make two renders differ is fixed (hash salt, text kept as text, no date
in the metadata, no display needed), so the same results always give the same bytes.
matplotlib is imported inside ``render_chart`` so that other commands do not pay for it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

from aml.graph.bench.model import STATUS_OK, BenchCell, BenchResult

HASH_SALT = "aml-bench"
PANEL_SIZE = (5.0, 3.6)  # inches per panel
MAX_COLUMNS = 2
Y_LABEL = "median ms (log scale)"


def _panels(results: Sequence[BenchResult]) -> list[tuple[str, list[BenchCell]]]:
    """(title, cells) per result file and account, at the largest T of that file."""
    panels: list[tuple[str, list[BenchCell]]] = []
    for result in results:
        meta = result.meta
        hours = max((c.hours for c in result.cells), default=0)
        for account in dict.fromkeys(c.account for c in result.cells):
            cells = [c for c in result.cells if c.account == account and c.hours == hours]
            title = f"{meta['profile']} / {meta['backend']} / {account}, T={hours} h"
            panels.append((title, cells))
    return panels


def render_chart(results: Sequence[BenchResult], path: Path) -> Path:
    """Write the SVG to ``path``; a method with no ``ok`` cell in a panel has no line."""
    from matplotlib import rc_context
    from matplotlib.figure import Figure

    panels = _panels(results) or [("no results", [])]
    columns = min(MAX_COLUMNS, len(panels))
    rows = math.ceil(len(panels) / columns)
    with rc_context({"svg.hashsalt": HASH_SALT, "svg.fonttype": "none"}):
        fig = Figure(figsize=(PANEL_SIZE[0] * columns, PANEL_SIZE[1] * rows), layout="constrained")
        axes = fig.subplots(rows, columns, squeeze=False)
        for index, (title, cells) in enumerate(panels):
            ax = axes[index // columns][index % columns]
            ax.set_title(title, fontsize=9)
            ax.set_xlabel("hops")
            ax.set_ylabel(Y_LABEL)
            ax.set_yscale("log")
            for method in dict.fromkeys(c.method for c in cells):
                ok = [c for c in cells if c.method == method and c.status == STATUS_OK]
                if ok:
                    exact = ok[0].exact  # an approximate method must not read as the fastest
                    ax.plot(
                        [c.hops for c in ok],
                        [c.median_ms for c in ok],
                        marker="o",
                        linestyle="-" if exact else "--",
                        label=method if exact else f"{method} (approximate)",
                    )
            if ax.get_legend_handles_labels()[0]:
                ax.set_xticks(sorted({c.hops for c in cells}))
                ax.legend(fontsize=8)
            else:
                ax.text(0.5, 0.5, "no timed cells", ha="center", va="center")
        for index in range(len(panels), rows * columns):
            axes[index // columns][index % columns].set_axis_off()
        fig.savefig(path, format="svg", metadata={"Date": None})
    return path
