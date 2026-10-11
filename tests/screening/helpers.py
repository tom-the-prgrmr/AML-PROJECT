"""Helpers for the Phase 3a tests (specs/screening-normalize-score.md): lazy module access, BASE."""

from __future__ import annotations

import importlib
from typing import Any

from aml.common.config import Settings, load_settings

BASE = (
    "Nguyễn Văn An",
    "Nguyễn Văn Bình",
    "Nguyễn Thị Hoa",
    "Trần Văn Long",
    "Trần Hữu Long",
    "Lê Thị Hoa",
    "Phạm Quốc Bảo",
    "Đỗ Xuân Sơn",
)


def mod(name: str) -> Any:
    return importlib.import_module(name)


def default_settings() -> Settings:
    return load_settings(environ={})


def screening_cfg() -> Any:
    return default_settings().screening


def norm(raw: Any, cfg: Any) -> str:
    return mod("aml.screening.normalize").normalize_name(raw, cfg)


def base_stats(cfg: Any) -> Any:
    names = [norm(n, cfg) for n in BASE]
    return mod("aml.screening.idf").build_token_stats(names)
