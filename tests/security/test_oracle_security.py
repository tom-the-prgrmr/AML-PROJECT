"""AC5-AC10 for specs/oracle-security.md (need a running Oracle plus ORACLE_SYS_PASSWORD and
ORACLE_DEMO_PASSWORD; the fixtures skip with a message naming the missing variable)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import OracleDb

from .helpers import ROLES, admin_db, demo_db, mod, normalise_masked, scalar

pytestmark = pytest.mark.oracle

USERS = [f"{r}_usr" for r in ROLES]
POLICIES = ["aml_pii_access", "aml_audit_log_tamper"]

READ_APP = [
    "customers", "customer_person", "admin_unit_mapping", "accounts", "transactions",
    "watchlist", "watchlist_alias", "acct_edge_daily", "customers_masked",
]  # fmt: skip
EXPECTED_GRANTS: dict[str, set[tuple[str, str]]] = {
    "aml_app": {("SELECT", t.upper()) for t in READ_APP} | {("INSERT", "AUDIT_LOG")},
    "aml_analyst": {
        ("SELECT", t.upper())
        for t in (
            "customers_masked",
            "accounts",
            "transactions",
            "acct_edge_daily",
            "watchlist",
            "watchlist_alias",
            "admin_unit_mapping",
        )
    },
    "aml_graph_sync": {
        ("SELECT", t.upper())
        for t in (
            "customers_masked",
            "accounts",
            "transactions",
            "acct_edge_daily",
            "graph_customer_attrs",
            "customer_golden",
            "admin_unit_mapping",
        )
    },
    "aml_auditor": {("SELECT", "AUDIT_LOG")},
}


def _count_applied(db: OracleDb) -> int:
    df = db.query_df(
        "SELECT COUNT(*) AS n FROM audit_log WHERE module = 'dba' "
        "AND entity_type = 'security' AND decision = 'SECURITY_APPLIED'"
    )
    return int(df.iloc[0, 0])


def _fails(db: OracleDb, sql: str, code: str) -> None:
    with pytest.raises(Exception, match=code):
        db.execute(sql) if not sql.lstrip().upper().startswith("SELECT") else db.query_df(sql)


def test_ac5_apply_security_is_idempotent_and_creates_everything(oracle_settings: Settings) -> None:
    security = mod("aml.dba.security")
    owner = oracle_settings.db.oracle.user
    with OracleDb(oracle_settings) as db:
        before = _count_applied(db)
    expected = {
        "roles": list(ROLES),
        "users": USERS,
        "policies": POLICIES,
    }
    assert security.apply_security(oracle_settings) == expected
    assert security.apply_security(oracle_settings) == expected

    with OracleDb(oracle_settings) as db:
        df = db.query_df(
            "SELECT details FROM (SELECT JSON_SERIALIZE(details) AS details, audit_id FROM "
            "audit_log WHERE module = 'dba' AND entity_type = 'security' "
            "AND decision = 'SECURITY_APPLIED' ORDER BY audit_id DESC) WHERE ROWNUM <= 2"
        )
        assert _count_applied(db) == before + 2
    assert len(df) == 2
    for raw in df["details"]:
        assert {r.lower() for r in json.loads(raw)["roles"]} == set(ROLES)

    with admin_db() as adm:
        roles = set(adm.query_df("SELECT role FROM dba_roles")["role"])
        assert {r.upper() for r in ROLES} <= roles
        users = adm.query_df("SELECT username, account_status FROM dba_users")
        status = dict(zip(users["username"], users["account_status"], strict=True))
        for u in USERS:
            assert status.get(u.upper()) == "OPEN", u
        policies = adm.query_df(
            "SELECT policy_name FROM audit_unified_enabled_policies "
            "WHERE policy_name LIKE 'AML\\_%' ESCAPE '\\'"
        )
        assert sorted(set(policies["policy_name"])) == sorted(p.upper() for p in POLICIES)
    assert owner  # owner name is configured

    for role in ROLES:
        with demo_db(role) as db:
            assert scalar(db, "SELECT 1 FROM dual") == 1


def test_ac6_role_and_user_privileges_are_least_privilege(secured: Settings) -> None:
    security = mod("aml.dba.security")
    owner = secured.db.oracle.user.upper()
    sizes = {"aml_app": 10, "aml_analyst": 7, "aml_graph_sync": 7, "aml_auditor": 1}
    for role in ROLES:
        normalised = {(p.upper(), o.upper()) for p, o in security.ROLE_GRANTS[role]}
        assert normalised == EXPECTED_GRANTS[role], role
        assert len(normalised) == sizes[role]

    with admin_db() as adm:
        for role in ROLES:
            tab = adm.query_df(
                "SELECT privilege, table_name FROM dba_tab_privs "
                f"WHERE grantee = '{role.upper()}' AND owner = '{owner}'"
            )
            got = set(zip(tab["privilege"], tab["table_name"], strict=True))
            assert got == EXPECTED_GRANTS[role], role
            sysp = adm.query_df(f"SELECT * FROM dba_sys_privs WHERE grantee = '{role.upper()}'")
            assert len(sysp) == 0, role
            rp = adm.query_df(
                f"SELECT granted_role FROM dba_role_privs WHERE grantee = '{role.upper()}'"
            )
            want = {"AUDIT_VIEWER"} if role == "aml_auditor" else set()
            assert set(rp["granted_role"]) == want, role

            user = f"{role}_usr".upper()
            sysp = adm.query_df(f"SELECT privilege FROM dba_sys_privs WHERE grantee = '{user}'")
            assert set(sysp["privilege"]) == {"CREATE SESSION"}, user
            rp = adm.query_df(f"SELECT granted_role FROM dba_role_privs WHERE grantee = '{user}'")
            assert set(rp["granted_role"]) == {role.upper()}, user
            tab = adm.query_df(f"SELECT * FROM dba_tab_privs WHERE grantee = '{user}'")
            assert len(tab) == 0, user


def test_ac7_analyst_sees_only_masked_customers(secured: Settings) -> None:
    owner = secured.db.oracle.user
    with demo_db("aml_analyst") as db:
        assert int(scalar(db, f"SELECT COUNT(*) FROM {owner}.customers_masked")) == 300
        for table in ("customers", "customer_person", "ground_truth", "audit_log"):
            _fails(db, f"SELECT COUNT(*) FROM {owner}.{table}", "ORA-00942")


def test_ac7_graph_sync_reads_edges_but_cannot_write(secured: Settings) -> None:
    owner = secured.db.oracle.user
    with demo_db("aml_graph_sync") as db:
        assert int(scalar(db, f"SELECT COUNT(*) FROM {owner}.acct_edge_daily")) >= 1
        _fails(
            db,
            f"INSERT INTO {owner}.transactions (txn_id, txn_ts, from_account_id, amount_vnd, "
            "channel) VALUES ('T_SEC', TIMESTAMP '2026-01-15 10:00:00', 'A1', 1000, 'CASH')",
            "ORA-01031|ORA-41900",
        )
        _fails(db, f"UPDATE {owner}.transactions SET amount_vnd = 1", "ORA-01031|ORA-41900")
        _fails(db, f"DELETE FROM {owner}.transactions", "ORA-01031|ORA-41900")
        _fails(db, f"SELECT COUNT(*) FROM {owner}.customers", "ORA-00942")


def test_ac7_app_reads_customers_and_only_appends_audit(secured: Settings) -> None:
    owner = secured.db.oracle.user
    with demo_db("aml_app") as db:
        assert int(scalar(db, f"SELECT COUNT(*) FROM {owner}.customers")) == 300
        db.execute(
            f"INSERT INTO {owner}.audit_log (event_ts, module, entity_type, entity_id, "
            "decision, reason, actor) VALUES (SYSTIMESTAMP, 'security_test', 'test', 'x', "
            "'TEST', 'AC7 insert by aml_app', 'pytest')"
        )
        _fails(db, f"SELECT COUNT(*) FROM {owner}.audit_log", "ORA-01031|ORA-41900")
        _fails(db, f"DELETE FROM {owner}.customers", "ORA-01031|ORA-41900")


def test_ac7_auditor_reads_audit_log_only(secured: Settings) -> None:
    owner = secured.db.oracle.user
    with demo_db("aml_auditor") as db:
        assert int(scalar(db, f"SELECT COUNT(*) FROM {owner}.audit_log")) >= 1
        _fails(
            db,
            f"INSERT INTO {owner}.audit_log (event_ts, module, entity_type, entity_id, "
            "decision, reason, actor) VALUES (SYSTIMESTAMP, 'security_test', 'test', 'x', "
            "'TEST', 'AC7 insert by auditor', 'pytest')",
            "ORA-01031|ORA-41900",
        )
        for table in ("customers_masked", "transactions"):
            _fails(db, f"SELECT COUNT(*) FROM {owner}.{table}", "ORA-00942")


def test_ac8_audit_log_is_append_only(secured: Settings) -> None:
    owner = secured.db.oracle.user
    with OracleDb(secured) as db:
        audit(db, module="security_test", entity_type="test", entity_id="ac8",
              decision="TEST", reason="AC8 seed row")  # fmt: skip
        n = int(scalar(db, "SELECT COUNT(*) FROM audit_log"))
        assert n >= 1
        for sql in (
            "UPDATE audit_log SET reason = 'x'",
            "DELETE FROM audit_log",
            "DELETE FROM audit_log WHERE 1 = 0",
        ):
            with pytest.raises(Exception, match="ORA-20100") as exc:
                db.execute(sql)
            assert "audit_log is append-only" in str(exc.value)
        _fails(db, "TRUNCATE TABLE audit_log", "ORA-20101")
        assert int(scalar(db, "SELECT COUNT(*) FROM audit_log")) == n

        audit(db, module="security_test", entity_type="test", entity_id="ac8",
              decision="TEST", reason="AC8 row after tamper attempts")  # fmt: skip
        assert int(scalar(db, "SELECT COUNT(*) FROM audit_log")) == n + 1

        trg = db.query_df("SELECT trigger_name, status FROM user_triggers")
        status = dict(zip(trg["trigger_name"], trg["status"], strict=True))
        for name in ("TRG_AUDIT_LOG_APPEND_ONLY", "TRG_AUDIT_LOG_NO_TRUNCATE"):
            assert status.get(name) == "ENABLED", name

    with demo_db("aml_app") as app:
        _fails(app, f"UPDATE {owner}.audit_log SET reason = 'x'", "ORA-01031|ORA-41900")


def test_ac9_unified_audit_records_pii_access_and_tampering(secured: Settings) -> None:
    owner = secured.db.oracle.user
    upper = owner.upper()
    filters = {
        "analyst_select": (
            "dbusername = 'AML_ANALYST_USR' AND action_name = 'SELECT' "
            "AND object_name = 'CUSTOMERS_MASKED' "
            "AND unified_audit_policies LIKE '%AML_PII_ACCESS%' AND return_code = 0"
        ),
        "owner_select": (
            f"dbusername = '{upper}' AND action_name = 'SELECT' AND object_name = 'CUSTOMERS' "
            "AND unified_audit_policies LIKE '%AML_PII_ACCESS%'"
        ),
        "owner_delete": (
            f"dbusername = '{upper}' AND action_name = 'DELETE' AND object_name = 'AUDIT_LOG' "
            "AND unified_audit_policies LIKE '%AML_AUDIT_LOG_TAMPER%' AND return_code = 20100"
        ),
    }

    def counts(db: OracleDb) -> dict[str, int]:
        return {
            k: int(scalar(db, f"SELECT COUNT(*) FROM unified_audit_trail WHERE {w}"))
            for k, w in filters.items()
        }

    with demo_db("aml_auditor") as auditor:
        before = counts(auditor)

        with demo_db("aml_analyst") as analyst:
            assert int(scalar(analyst, f"SELECT COUNT(*) FROM {owner}.customers_masked")) == 300
            _fails(analyst, "SELECT COUNT(*) FROM unified_audit_trail", "ORA-00942")
        with OracleDb(secured) as own:
            scalar(own, "SELECT COUNT(*) FROM customers")
            _fails(own, "DELETE FROM audit_log", "ORA-20100")

        after = counts(auditor)
    for key in filters:
        assert after[key] >= before[key] + 1, key


def test_ac10_oracle_masked_view_matches_python_reference(
    secured: Settings, tiny_parquet: Path
) -> None:
    with OracleDb(secured) as db:
        view = normalise_masked(db.query_df("SELECT * FROM customers_masked ORDER BY cif"))
    assert list(view.columns) == list(mod("aml.dba.masking").MASKED_COLUMNS)
    assert len(view) == 300

    customers = pd.read_parquet(tiny_parquet / "customers.parquet")
    customers = customers.sort_values("cif").reset_index(drop=True)
    expected: Any = normalise_masked(mod("aml.dba.masking").mask_customers(customers))
    pd.testing.assert_frame_equal(view, expected)
