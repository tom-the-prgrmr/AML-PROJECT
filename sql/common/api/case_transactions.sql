-- Phase 9b: the transactions behind the ACTIVE RULE / NETWORK items of the latest case run.
-- One row per (case, item, transaction); the caller appends the case filter, groups by transaction,
-- masks and pages. device_id and ip are never selected. Plain SQL, valid on DuckDB and Oracle.
SELECT ca.case_id,
       ca.item_key,
       t.txn_id,
       t.txn_ts,
       t.from_account_id,
       t.to_account_id,
       t.amount_vnd,
       t.channel,
       t.memo,
       t.counterparty_name
FROM case_alerts_current ca
JOIN alerts a ON CAST(a.alert_id AS VARCHAR(80)) = ca.alert_ref
JOIN alert_evidence e ON e.alert_id = a.alert_id
JOIN transactions t ON t.txn_id = e.txn_id
WHERE ca.status = 'ACTIVE'
  AND ca.source IN ('RULE', 'NETWORK')
  AND ca.case_id IS NOT NULL
