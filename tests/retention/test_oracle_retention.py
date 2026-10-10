"""AC4-AC9 for specs/oracle-retention.md (need a running Oracle; shared dev schema aml_owner).

audit_log is append-only on Oracle (triggers), so tests never delete audit rows: they remember
``max(audit_id)`` before acting and look only at rows above it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.audit import AuditEvent, audit_many
from aml.common.config import Settings
from aml.common.db import OracleDb
from aml.datagen.transactions import TRANSACTION_COLUMNS

from .conftest import audit_rows
from .helpers import (
    count_txn,
    max_audit_id,
    mod,
    partition_highs,
    scalar,
)

pytestmark = pytest.mark.oracle

AS_OF = date(2026, 6, 30)
CUTOFF = datetime(2021, 6, 1)
OLD_HIGHS = {"2019-04-01T00:00:00", "2019-05-01T00:00:00"}


def _new(db: OracleDb, since: int, where: str) -> pd.DataFrame:
    return audit_rows(db, f"audit_id > {since} AND module = 'dba' AND {where}")


def _purge(db: OracleDb, settings: Settings, *, dry_run: bool) -> Any:
    return mod("aml.dba.retention").purge_transactions(db, settings, as_of=AS_OF, dry_run=dry_run)


def _parquet_files(root: Path) -> list[Path]:
    return list(root.rglob("*.parquet")) if root.exists() else []


def test_ac4_audit_log_partitioned_non_destructively(rt_settings: Settings) -> None:
    schema = mod("aml.dba.schema")
    tag = f"AC4-{uuid.uuid4().hex}"
    with OracleDb(rt_settings) as db:
        schema.apply_schema(db)  # make sure audit_log exists
        total_before = int(scalar(db, "SELECT COUNT(*) FROM audit_log"))
        audit_many(
            db,
            [
                AuditEvent(
                    module="test",
                    entity_type="test",
                    entity_id=f"{tag}-{i}",
                    decision="TEST",
                    reason="AC4 audit sample",
                    event_ts=datetime(2026, m, 15, tzinfo=UTC),
                )
                for i, m in enumerate((1, 2, 3))
            ],
        )

        schema.apply_schema(db)
        schema.apply_schema(db)

        part = db.query_df(
            'SELECT partitioning_type, "INTERVAL" AS iv FROM user_part_tables '
            "WHERE table_name = 'AUDIT_LOG'"
        ).iloc[0]
        assert part["partitioning_type"] == "RANGE"
        assert part["iv"].replace(" ", "") == "NUMTOYMINTERVAL(1,'MONTH')"
        keys = db.query_df(
            "SELECT column_name FROM user_part_key_columns "
            "WHERE name = 'AUDIT_LOG' AND object_type = 'TABLE' ORDER BY column_position"
        )
        assert list(keys["column_name"]) == ["EVENT_TS"]
        assert "P_BEFORE_2000" in partition_highs(db, "AUDIT_LOG")

        pk = db.query_df(
            "SELECT i.partitioned, i.status FROM user_indexes i JOIN user_constraints c "
            "ON c.index_name = i.index_name WHERE c.table_name = 'AUDIT_LOG' "
            "AND c.constraint_type = 'P'"
        )
        assert list(pk["partitioned"]) == ["NO"]
        assert list(pk["status"]) == ["VALID"]

        assert (
            int(scalar(db, f"SELECT COUNT(*) FROM audit_log WHERE entity_id LIKE '{tag}-%'")) == 3
        )
        assert int(scalar(db, "SELECT COUNT(*) FROM audit_log")) >= total_before + 3

        trg = db.query_df(
            "SELECT t.trigger_name, t.status, o.status AS obj_status FROM user_triggers t "
            "JOIN user_objects o ON o.object_name = t.trigger_name AND o.object_type = 'TRIGGER' "
            "WHERE t.trigger_name IN ('TRG_AUDIT_LOG_APPEND_ONLY', 'TRG_AUDIT_LOG_NO_TRUNCATE')"
        )
        assert sorted(trg["trigger_name"]) == [
            "TRG_AUDIT_LOG_APPEND_ONLY",
            "TRG_AUDIT_LOG_NO_TRUNCATE",
        ]
        assert set(trg["status"]) == {"ENABLED"}
        assert set(trg["obj_status"]) == {"VALID"}

        converted = audit_rows(
            db,
            "module = 'dba' AND entity_type = 'table' AND entity_id = 'audit_log' "
            "AND decision = 'PARTITIONED'",
        )
        assert len(converted) == 1


def test_ac5_dry_run_plans_without_dropping(rt_db: OracleDb, rt_settings: Settings) -> None:
    parts_before = int(
        scalar(rt_db, "SELECT COUNT(*) FROM user_tab_partitions WHERE table_name = 'TRANSACTIONS'")
    )
    since = max_audit_id(rt_db)

    plan = _purge(rt_db, rt_settings, dry_run=True)

    assert plan.executed is False
    assert plan.cutoff == CUTOFF
    assert [a.month for a in plan.drop] == ["2019-03", "2019-04"]
    assert [a.rows for a in plan.drop] == [1, 1]
    assert all(a.partition != "P_BEFORE_2000" for a in plan.drop)
    parts_after = int(
        scalar(rt_db, "SELECT COUNT(*) FROM user_tab_partitions WHERE table_name = 'TRANSACTIONS'")
    )
    assert parts_after == parts_before
    assert count_txn(rt_db, "RT1") == 1
    assert count_txn(rt_db, "RT2") == 1
    assert _parquet_files(Path(rt_settings.retention.archive_dir)) == []

    rows = _new(rt_db, since, "entity_type = 'table' AND entity_id = 'transactions'")
    assert list(rows["decision"]) == ["RETENTION_DRY_RUN"]
    details = rows.iloc[0]["details"]
    assert details["months"] == ["2019-03", "2019-04"]
    assert details["cutoff"] == "2021-06-01"
    assert details["retention_months"] == 60


def test_ac6_execute_archives_then_drops(rt_db: OracleDb, rt_settings: Settings) -> None:
    archive = Path(rt_settings.retention.archive_dir)

    plan = _purge(rt_db, rt_settings, dry_run=False)

    assert plan.executed is True
    for month, txn_id in (("2019-03", "RT1"), ("2019-04", "RT2")):
        df = pd.read_parquet(archive / "transactions" / f"transactions_{month}.parquet")
        assert list(df.columns) == TRANSACTION_COLUMNS
        assert list(df["txn_id"]) == [txn_id]
    assert (
        int(scalar(rt_db, "SELECT COUNT(*) FROM transactions WHERE txn_id IN ('RT1','RT2')")) == 0
    )
    assert not (set(partition_highs(rt_db).values()) & OLD_HIGHS)
    assert "P_BEFORE_2000" in partition_highs(rt_db)
    assert count_txn(rt_db, "RT3") == 1
    pk_status = scalar(
        rt_db,
        "SELECT i.status FROM user_indexes i JOIN user_constraints c "
        "ON c.index_name = i.index_name WHERE c.table_name = 'TRANSACTIONS' "
        "AND c.constraint_type = 'P'",
    )
    assert pk_status == "VALID"


def test_ac7_execute_audits_each_drop_refreshes_mview_once_and_is_idempotent(
    rt_db: OracleDb, rt_settings: Settings
) -> None:
    archive = Path(rt_settings.retention.archive_dir)
    since = max_audit_id(rt_db)

    _purge(rt_db, rt_settings, dry_run=False)

    drops = _new(rt_db, since, "decision = 'PARTITION_DROPPED'")
    assert list(drops["entity_type"]) == ["partition", "partition"]
    assert list(drops["entity_id"]) == ["transactions:2019-03", "transactions:2019-04"]
    for month, (_, row) in zip(("2019-03", "2019-04"), drops.iterrows(), strict=True):
        details = row["details"]
        assert details["rows"] == 1
        assert Path(details["archive_path"]) == archive / "transactions" / (
            f"transactions_{month}.parquet"
        )
        assert details["cutoff"] == "2021-06-01"
        assert details["retention_months"] == 60
    reason_col = rt_db.query_df(
        f"SELECT reason FROM audit_log WHERE audit_id > {since} AND module = 'dba' "
        "AND decision = 'PARTITION_DROPPED'"
    ).iloc[:, 0]
    assert all("UPDATE GLOBAL INDEXES" in r for r in reason_col)

    refreshed = _new(rt_db, since, "entity_id = 'acct_edge_daily' AND decision = 'REFRESHED'")
    assert len(refreshed) == 1

    since2 = max_audit_id(rt_db)
    again = _purge(rt_db, rt_settings, dry_run=False)
    assert again.drop == ()
    extra = _new(rt_db, since2, "decision IN ('PARTITION_DROPPED', 'REFRESHED')")
    assert len(extra) == 0


def test_ac8_failure_midway_keeps_earlier_drop_and_later_partition(
    rt_db: OracleDb, rt_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = Path(rt_settings.retention.archive_dir)
    original = pd.DataFrame.to_parquet

    def flaky(self: pd.DataFrame, path: Any = None, *args: Any, **kwargs: Any) -> Any:
        if "2019-04" in str(path):
            raise OSError("disk full")
        return original(self, path, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", flaky)
    since = max_audit_id(rt_db)

    with pytest.raises(OSError, match="disk full"):
        _purge(rt_db, rt_settings, dry_run=False)

    assert "2019-04-01T00:00:00" not in set(partition_highs(rt_db).values())
    assert count_txn(rt_db, "RT1") == 0
    assert count_txn(rt_db, "RT2") == 1
    dropped = _new(rt_db, since, "decision = 'PARTITION_DROPPED'")
    assert list(dropped["entity_id"]) == ["transactions:2019-03"]
    assert not (archive / "transactions" / "transactions_2019-04.parquet").exists()


def test_ac9_audit_log_is_never_purged(rt_db: OracleDb, rt_settings: Settings) -> None:
    retention = mod("aml.dba.retention")
    entity = f"RETENTION-AUDIT-{uuid.uuid4().hex}"
    audit_many(
        rt_db,
        [
            AuditEvent(
                module="test",
                entity_type="test",
                entity_id=entity,
                decision="TEST",
                reason="old audit event that must survive the purge",
                event_ts=datetime(2019, 3, 10, 8, 0, 0, tzinfo=UTC),
            )
        ],
    )

    _purge(rt_db, rt_settings, dry_run=False)

    assert count_txn(rt_db, "RT1") == 0
    assert int(scalar(rt_db, f"SELECT COUNT(*) FROM audit_log WHERE entity_id = '{entity}'")) == 1
    audit_highs = partition_highs(rt_db, "AUDIT_LOG")
    assert any(h.startswith("2019-04-01T00:00:00") for h in audit_highs.values())

    before = (partition_highs(rt_db), audit_highs)
    with pytest.raises(retention.RetentionError, match="audit_log is excluded from purge"):
        retention.purge_transactions(rt_db, rt_settings, table="audit_log")
    assert (partition_highs(rt_db), partition_highs(rt_db, "AUDIT_LOG")) == before
