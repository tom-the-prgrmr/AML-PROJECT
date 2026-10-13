"""Median and percentile in plain Python (linear interpolation, the NumPy default)."""

from __future__ import annotations

import math
from collections.abc import Sequence


def percentile(values: Sequence[float], q: float) -> float:
    """The q-th percentile (0..100), interpolated at rank ``(n - 1) * q / 100``."""
    if not values:
        raise ValueError("percentile of an empty sequence")
    if not 0 <= q <= 100:
        raise ValueError(f"q must be between 0 and 100, got {q}")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q / 100
    low = math.floor(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def median(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("median of an empty sequence")
    return percentile(values, 50)
