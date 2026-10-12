"""Maintain the Oracle vertex table (``acct_node``) of the ``aml_fund_flow`` property graph."""

from __future__ import annotations

from aml.common.db import Database


def refresh_account_nodes(db: Database) -> int:
    """Rebuild ``acct_node`` (Oracle) and return its row count; DuckDB has no such table: 0.

    No audit row: it is a technical helper, ``acct_edge_daily`` already audits its own refresh.
    """
    if db.backend != "oracle":
        return 0
    db.execute("BEGIN DBMS_MVIEW.REFRESH('ACCT_NODE', 'C', atomic_refresh => FALSE); END;")
    db.execute("BEGIN DBMS_STATS.GATHER_TABLE_STATS(ownname => USER, tabname => 'ACCT_NODE'); END;")
    return int(db.query_df("SELECT COUNT(*) AS n FROM acct_node").iloc[0, 0])
