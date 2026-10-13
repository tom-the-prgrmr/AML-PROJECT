-- Phase 7a: one row per transaction leg of one golden customer in a window, with the golden
-- customer that owns the counterparty account (NULL for external accounts and cash legs).
-- Placeholders as in txn_summary.sql. aml.cases.enrich_txn ranks the counterparties and keeps the
-- transaction ids (for the data quality counts) from these rows.
SELECT l.txn_id          AS txn_id,
       l.counterparty_id AS counterparty_id,
       l.direction       AS direction,
       l.amount_vnd      AS amount_vnd,
       CASE WHEN a.cif IS NULL THEN NULL
            ELSE COALESCE(g.golden_customer_id, 'G-' || a.cif) END AS golden_customer_id
FROM txn_legs l
LEFT JOIN accounts a ON a.account_id = l.counterparty_id
LEFT JOIN customer_golden g ON g.cif = a.cif
WHERE {cif_filter}
  AND l.txn_ts >= {window_start}
  AND l.txn_ts < {window_end_next}
