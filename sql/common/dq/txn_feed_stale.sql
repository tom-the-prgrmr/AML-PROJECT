-- TXN_FEED_STALE: table-level check, the newest transaction is older than as_of minus the lag.
SELECT 'transactions' AS entity_id
FROM (SELECT MAX(txn_ts) AS newest_ts FROM transactions) m
WHERE m.newest_ts < {as_of} - {max_feed_lag_days};
