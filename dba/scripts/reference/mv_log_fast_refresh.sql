-- REFERENCE ONLY: never run here. A MATERIALIZED VIEW LOG on transactions slows every DML and
-- bulk reload, which is why acct_edge_daily stays REFRESH COMPLETE ON DEMAND
-- (see sql/oracle/ddl/040_acct_edge_daily.sql). Sketch of what REFRESH FAST would need.
CREATE MATERIALIZED VIEW LOG ON transactions
  WITH ROWID, SEQUENCE (from_account_id, to_account_id, txn_ts, amount_vnd)
  INCLUDING NEW VALUES
/
-- COUNT(*) and COUNT(amount_vnd) are mandatory next to SUM(amount_vnd) for fast refresh.
CREATE MATERIALIZED VIEW acct_edge_daily_fast
  BUILD IMMEDIATE REFRESH FAST ON DEMAND
AS
SELECT from_account_id AS src_acct,
       to_account_id   AS dst_acct,
       TRUNC(txn_ts)   AS day,
       COUNT(*)        AS txn_count,
       COUNT(amount_vnd) AS amount_count,
       SUM(amount_vnd) AS total_amount
FROM transactions
WHERE from_account_id IS NOT NULL AND to_account_id IS NOT NULL
GROUP BY from_account_id, to_account_id, TRUNC(txn_ts)
/
-- Diagnose why a MV is not fast-refreshable:
--   EXEC DBMS_MVIEW.EXPLAIN_MVIEW('ACCT_EDGE_DAILY_FAST')
--   SELECT capability_name, possible, msgtxt FROM mv_capabilities_table
BEGIN
  DBMS_MVIEW.REFRESH('ACCT_EDGE_DAILY_FAST', 'F');
END;
/
