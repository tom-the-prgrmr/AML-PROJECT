import json

import pytest
from pydantic import ValidationError

from aml.common.audit import AuditEvent, audit, audit_many
from aml.common.config import load_settings
from aml.common.db import DuckDb, OracleDb


def _init(db) -> None:
    db.run_named_script("ddl/000_audit_log.sql")


def test_audit_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        AuditEvent(module="m", entity_type="t", entity_id="1", decision="ALERT", reason="")


def test_audit_roundtrip_with_details(duck: DuckDb) -> None:
    _init(duck)
    audit(
        duck,
        module="screening",
        entity_type="customer",
        entity_id="CIF0001",
        decision="AUTO_CLEARED",
        reason="DOB mismatch > 5y",
        version="screening-v1",
        details={"watchlist_id": "WL42", "score": 0.91, "ghi_chú": "tiếng Việt"},
    )
    row = duck.query_df("SELECT * FROM audit_log").iloc[0]
    assert row["actor"] == "system"
    assert row["reason"] == "DOB mismatch > 5y"
    assert json.loads(row["details"])["ghi_chú"] == "tiếng Việt"


def test_audit_many_batches_and_is_idempotent_ddl(duck: DuckDb) -> None:
    _init(duck)
    _init(duck)  # DDL is re-runnable
    events = [
        AuditEvent(
            module="monitoring", entity_type="alert", entity_id=str(i),
            decision="ALERT", reason="structuring: 3 cash deposits 90-99% of threshold",
        )
        for i in range(500)
    ]  # fmt: skip
    assert audit_many(duck, events) == 500
    assert audit_many(duck, []) == 0
    assert duck.query_df("SELECT COUNT(DISTINCT audit_id) AS n FROM audit_log")["n"][0] == 500


@pytest.mark.oracle
def test_audit_on_oracle() -> None:
    with OracleDb(load_settings()) as db:
        _init(db)
        audit(
            db, module="test", entity_type="probe", entity_id="pytest",
            decision="OK", reason="oracle audit smoke test", details={"k": "v"},
        )  # fmt: skip
        n = db.query_df("SELECT COUNT(*) AS n FROM audit_log WHERE entity_id = 'pytest'")["n"][0]
        assert n >= 1
