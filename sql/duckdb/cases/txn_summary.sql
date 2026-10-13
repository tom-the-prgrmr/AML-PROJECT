-- Phase 7a: transaction summary of one golden customer over a window, from txn_legs.
-- {cif_filter}, {window_start} and {window_end_next} are formatted by aml.cases.enrich_txn from
-- typed values (quoted CIFs, DATE literals); the window is [window_start, window_end_next).
-- ROLLUP gives one row per channel plus one total row (is_total = 1) in a single pass.
SELECT GROUPING(l.channel)                                                       AS is_total,
       l.channel                                                                 AS channel,
       COUNT(DISTINCT l.txn_id)                                                  AS txn_count,
       COUNT(DISTINCT CASE WHEN l.direction = 'IN' THEN l.txn_id END)            AS in_count,
       COUNT(DISTINCT CASE WHEN l.direction = 'OUT' THEN l.txn_id END)           AS out_count,
       CAST(COALESCE(SUM(CASE WHEN l.direction = 'IN' THEN l.amount_vnd END), 0) AS BIGINT)
                                                                                 AS in_vnd,
       CAST(COALESCE(SUM(CASE WHEN l.direction = 'OUT' THEN l.amount_vnd END), 0) AS BIGINT)
                                                                                 AS out_vnd,
       CAST(COALESCE(SUM(CASE WHEN l.direction = 'IN' AND l.channel = 'CASH'
                              THEN l.amount_vnd END), 0) AS BIGINT)              AS cash_in_vnd,
       CAST(COALESCE(SUM(CASE WHEN l.direction = 'OUT' AND l.channel = 'CASH'
                              THEN l.amount_vnd END), 0) AS BIGINT)              AS cash_out_vnd,
       COUNT(DISTINCT l.counterparty_id)                                         AS counterparties,
       CAST(COALESCE(MAX(l.amount_vnd), 0) AS BIGINT)                            AS max_txn_vnd,
       COUNT(DISTINCT CAST(l.txn_ts AS DATE))                                    AS active_days,
       CAST(COALESCE(SUM(l.amount_vnd), 0) AS BIGINT)                            AS vnd
FROM txn_legs l
WHERE {cif_filter}
  AND l.txn_ts >= {window_start}
  AND l.txn_ts < {window_end_next}
GROUP BY ROLLUP (l.channel)
