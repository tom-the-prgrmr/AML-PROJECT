"""Deterministic, per-table random streams independent of ``PYTHONHASHSEED``."""

from __future__ import annotations

import hashlib

import numpy as np


def stable_hash(name: str) -> int:
    """Return a process-independent 64-bit integer hash of ``name`` (sha256, first 8 bytes)."""
    return int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big")


def table_rng(seed: int, table_name: str) -> np.random.Generator:
    """Return a generator seeded from ``seed`` and ``table_name``, isolated per table."""
    return np.random.default_rng(np.random.SeedSequence([seed, stable_hash(table_name)]))
