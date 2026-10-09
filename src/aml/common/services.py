"""Cheap reachability checks for optional services, used by the CLI and pytest skips."""

from __future__ import annotations

import socket
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from aml.common.config import Settings, get_settings


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    up: bool
    detail: str


def _tcp_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def oracle_status(settings: Settings | None = None) -> ServiceStatus:
    """Up only if we can actually log in (the listener opens long before the PDB is ready)."""
    settings = settings or get_settings()
    cfg = settings.db.oracle
    if not _tcp_open(cfg.host, cfg.port):
        return ServiceStatus("oracle", False, f"no listener on {cfg.host}:{cfg.port}")
    import oracledb

    try:
        with oracledb.connect(
            user=cfg.user, password=cfg.password, dsn=cfg.dsn, tcp_connect_timeout=3
        ) as con:
            return ServiceStatus("oracle", True, f"{cfg.dsn} (Oracle {con.version})")
    except oracledb.Error as exc:
        return ServiceStatus("oracle", False, f"listener up but login failed: {exc}")


def neo4j_status(settings: Settings | None = None) -> ServiceStatus:
    settings = settings or get_settings()
    cfg = settings.neo4j
    url = urlparse(cfg.uri)
    if not _tcp_open(url.hostname or "localhost", url.port or 7687):
        return ServiceStatus("neo4j", False, f"no bolt listener at {cfg.uri}")
    from neo4j import GraphDatabase

    try:
        with GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password)) as driver:
            info = driver.get_server_info()
            return ServiceStatus("neo4j", True, f"{cfg.uri} ({info.agent})")
    except Exception as exc:  # driver raises several unrelated exception types
        return ServiceStatus("neo4j", False, f"bolt up but connect failed: {exc}")


def ollama_status(settings: Settings | None = None) -> ServiceStatus:
    settings = settings or get_settings()
    host = settings.ollama.host.rstrip("/")
    try:
        with urllib.request.urlopen(f"{host}/api/version", timeout=2) as resp:
            return ServiceStatus("ollama", True, f"{host} {resp.read().decode()}")
    except OSError as exc:
        return ServiceStatus("ollama", False, f"{host} unreachable: {exc}")


def all_statuses(settings: Settings | None = None) -> list[ServiceStatus]:
    return [oracle_status(settings), neo4j_status(settings), ollama_status(settings)]
