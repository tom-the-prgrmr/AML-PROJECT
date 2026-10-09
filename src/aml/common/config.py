"""Typed configuration loaded from ``config.yaml`` with env-var overrides.

Secrets never live in ``config.yaml``: they come from the environment or from the
git-ignored ``.env`` file (real env vars win over ``.env``). The same ``.env`` is read by
docker-compose, so container and client credentials have a single source.

Override rules (applied in order):
1. ``AML__<SECTION>__<KEY>[__<SUBKEY>...]=value`` sets any nested key (YAML-parsed value).
2. Credential vars shared with docker-compose (see ``SECRET_ENV_MAP``).
3. ``DB_BACKEND=oracle|duckdb`` is a shortcut for ``db.backend``.
"""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DOTENV_PATH = PROJECT_ROOT / ".env"
ENV_PREFIX = "AML__"

# docker-compose variable -> config key path (raw strings, not YAML-parsed).
SECRET_ENV_MAP: dict[str, list[str]] = {
    "ORACLE_APP_USER": ["db", "oracle", "user"],
    "ORACLE_APP_PASSWORD": ["db", "oracle", "password"],
    "NEO4J_PASSWORD": ["neo4j", "password"],
}


class OracleConfig(BaseModel):
    host: str
    port: int
    service: str
    user: str
    password: str

    @property
    def dsn(self) -> str:
        return f"{self.host}:{self.port}/{self.service}"


class DbConfig(BaseModel):
    backend: Literal["oracle", "duckdb"]
    duckdb_path: str
    oracle: OracleConfig
    fallback_to_duckdb: bool = True


class Neo4jConfig(BaseModel):
    uri: str
    user: str
    password: str


class OllamaConfig(BaseModel):
    host: str
    llm_model: str
    embed_model: str


class ProfileConfig(BaseModel):
    customers: int
    transactions: int
    months: int
    counterparties: tuple[int, int]
    typology_scale: int = 1  # multiplies every data.typologies count


class WatchlistConfig(BaseModel):
    entries: int  # total watchlist rows (true hits and traps included)
    true_hits: int  # customers planted on the list (sanctions_hit / pep_hit)
    traps: int  # look-alike entries that match no customer (screening_trap)
    year_only_dob_rate: float  # share of entries with only a birth year
    unknown_dob_rate: float  # share of entries with no DOB information


class DataConfig(BaseModel):
    profile: Literal["small", "dense", "large"]
    output_dir: str
    reference_date: date
    start_date: date
    profiles: dict[str, ProfileConfig]
    duplicate_person_rate: float
    dq_defect_rate: float
    injection_memos: int
    typologies: dict[str, int]  # scenarios injected per typology (before profile scaling)
    watchlist: WatchlistConfig

    @property
    def active(self) -> ProfileConfig:
        return self.profiles[self.profile]


class ThresholdConfig(BaseModel):
    large_cash_vnd: int
    structuring_band_pct: float


class AuditConfig(BaseModel):
    system_actor: str = "system"


class Settings(BaseModel):
    seed: int
    db: DbConfig
    neo4j: Neo4jConfig
    ollama: OllamaConfig
    data: DataConfig
    thresholds: ThresholdConfig
    audit: AuditConfig

    def path(self, relative: str) -> Path:
        """Resolve a config path relative to the project root."""
        p = Path(relative)
        return p if p.is_absolute() else PROJECT_ROOT / p


def _set_nested(tree: dict[str, Any], keys: list[str], value: Any) -> None:
    node = tree
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value


def apply_env_overrides(raw: dict[str, Any], environ: dict[str, str]) -> dict[str, Any]:
    """Return ``raw`` with env-var overrides applied (mutates and returns ``raw``)."""
    for name, value in environ.items():
        if name.startswith(ENV_PREFIX):
            keys = [k.lower() for k in name[len(ENV_PREFIX) :].split("__") if k]
            if keys:
                _set_nested(raw, keys, yaml.safe_load(value))
    for name, keys in SECRET_ENV_MAP.items():
        if value := environ.get(name):
            _set_nested(raw, keys, value)
    if backend := environ.get("DB_BACKEND"):
        _set_nested(raw, ["db", "backend"], backend.strip().lower())
    return raw


def read_environ(dotenv_path: Path = DOTENV_PATH) -> dict[str, str]:
    """Process env layered over ``.env`` (process env wins, like docker-compose)."""
    merged = {k: v for k, v in dotenv_values(dotenv_path).items() if v is not None}
    merged.update(os.environ)
    return merged


def load_settings(
    path: Path = DEFAULT_CONFIG_PATH, environ: dict[str, str] | None = None
) -> Settings:
    """Load and validate settings from YAML plus environment (default: env + ``.env``)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = apply_env_overrides(raw, read_environ() if environ is None else environ)
    return Settings.model_validate(raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide cached settings."""
    return load_settings()
