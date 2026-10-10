-- Phase 2a: account->account daily edges for graph tracing (materialized view, complete refresh).
-- Refreshed by DBMS_MVIEW.REFRESH('ACCT_EDGE_DAILY','C', atomic_refresh => FALSE) after each load.

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE MATERIALIZED VIEW acct_edge_daily
      BUILD IMMEDIATE REFRESH COMPLETE ON DEMAND
    AS
    SELECT from_account_id AS src_acct,
           to_account_id   AS dst_acct,
           TRUNC(txn_ts)   AS day,
           COUNT(*)        AS txn_count,
           SUM(amount_vnd) AS total_amount
    FROM transactions
    WHERE from_account_id IS NOT NULL AND to_account_id IS NOT NULL
    GROUP BY from_account_id, to_account_id, TRUNC(txn_ts)]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE NOT IN (-955, -12006) THEN RAISE; END IF;   -- name used / MV already exists
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX ix_aed_src_day ON acct_edge_daily (src_acct, day)';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE NOT IN (-955, -1408) THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX ix_aed_dst_day ON acct_edge_daily (dst_acct, day)';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE NOT IN (-955, -1408) THEN RAISE; END IF;
END;
/
