"""Phase 2b security setup: least-privilege roles, demo users, unified audit policies.

Oracle only. ``apply_security`` connects as the admin user for role/user/policy DDL and as the
schema owner for grants (so the grants follow tables that tests drop and recreate). Passwords come
from ``.env`` through settings and are never written to a ``.sql`` file.
"""

from __future__ import annotations

import re

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import OracleDb
from aml.dba.schema import apply_schema

ROLES: tuple[str, ...] = ("aml_app", "aml_analyst", "aml_graph_sync", "aml_auditor")
DEMO_USERS: dict[str, str] = {role: f"{role}_usr" for role in ROLES}
AUDIT_POLICIES: tuple[str, ...] = ("aml_pii_access", "aml_audit_log_tamper")

_READ_APP = (
    "customers", "customer_person", "admin_unit_mapping", "accounts", "transactions",
    "watchlist", "watchlist_alias", "acct_edge_daily", "customers_masked",
)  # fmt: skip
_READ_ANALYST = (
    "customers_masked", "accounts", "transactions", "acct_edge_daily",
    "watchlist", "watchlist_alias", "admin_unit_mapping",
)  # fmt: skip
_READ_GRAPH = ("customers_masked", "accounts", "transactions", "acct_edge_daily")

# Keep in step with sql/oracle/security/020_grants.sql (the tests compare with dba_tab_privs).
ROLE_GRANTS: dict[str, frozenset[tuple[str, str]]] = {
    "aml_app": frozenset({("SELECT", t) for t in _READ_APP} | {("INSERT", "audit_log")}),
    "aml_analyst": frozenset(("SELECT", t) for t in _READ_ANALYST),
    "aml_graph_sync": frozenset(("SELECT", t) for t in _READ_GRAPH),
    "aml_auditor": frozenset({("SELECT", "audit_log")}),
}

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,29}$")


class SecurityConfigError(RuntimeError):
    """A required secret is missing or unusable; the message names the .env variable."""


def _check_config(settings: Settings) -> None:
    cfg = settings.db.oracle
    if settings.db.backend != "oracle":
        raise NotImplementedError(
            f"security-setup is Oracle only (active backend is {settings.db.backend})."
        )
    if not cfg.admin_password:
        raise SecurityConfigError("ORACLE_SYS_PASSWORD is not set in .env (admin login).")
    if not cfg.demo_password:
        raise SecurityConfigError("ORACLE_DEMO_PASSWORD is not set in .env (demo user password).")
    if '"' in cfg.demo_password:
        raise SecurityConfigError("ORACLE_DEMO_PASSWORD must not contain a double quote.")
    if not _IDENTIFIER.match(cfg.user):
        raise SecurityConfigError(f"Oracle owner {cfg.user!r} is not a plain identifier.")


def _login_as(settings: Settings, user: str, password: str) -> OracleDb:
    oracle = settings.db.oracle.model_copy(update={"user": user, "password": password})
    return OracleDb(
        settings.model_copy(update={"db": settings.db.model_copy(update={"oracle": oracle})})
    )


def _sync_demo_users(admin: OracleDb, password: str) -> None:
    """Create each demo user (or re-sync its password) with CREATE SESSION + exactly one role."""
    existing = set(
        admin.query_df("SELECT username FROM dba_users WHERE username LIKE 'AML%USR'")["username"]
    )
    for role, user in DEMO_USERS.items():
        verb = "ALTER" if user.upper() in existing else "CREATE"
        admin.execute(f'{verb} USER {user} IDENTIFIED BY "{password}"')
        admin.execute(f"ALTER USER {user} ACCOUNT UNLOCK")
        admin.execute(f"GRANT CREATE SESSION TO {user}")
        admin.execute(f"GRANT {role} TO {user}")


def apply_security(settings: Settings) -> dict[str, list[str]]:
    """Create/refresh roles, demo users, grants and audit policies (idempotent)."""
    _check_config(settings)
    cfg = settings.db.oracle
    owner = cfg.user

    with _login_as(settings, cfg.admin_user, cfg.admin_password) as admin:
        assert isinstance(admin, OracleDb)
        admin.run_named_script("security/010_roles_users.sql")
        _sync_demo_users(admin, cfg.demo_password)

    result = {
        "roles": list(ROLES),
        "users": [DEMO_USERS[r] for r in ROLES],
        "policies": list(AUDIT_POLICIES),
    }
    with OracleDb(settings) as owner_db:
        apply_schema(owner_db)
        owner_db.run_named_script("security/020_grants.sql")

        with _login_as(settings, cfg.admin_user, cfg.admin_password) as admin:
            admin.execute(f"ALTER SESSION SET CURRENT_SCHEMA = {owner}")
            admin.run_named_script("security/030_audit_policies.sql")

        audit(
            owner_db,
            module="dba",
            entity_type="security",
            entity_id="oracle",
            decision="SECURITY_APPLIED",
            reason=(
                f"Applied {len(ROLES)} least-privilege roles, {len(ROLES)} demo users, "
                f"object grants and {len(AUDIT_POLICIES)} unified audit policies "
                f"on schema {owner}."
            ),
            version="security",
            details=result,
        )
    return result
