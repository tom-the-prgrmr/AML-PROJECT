-- Phase 8d: the transactions of one case with their memo, one row per transaction. The window and
-- the CIFs are the ones the case snapshot stored (txn_summary, linked_cifs), so a later run counts
-- the same transactions. Placeholders as in cases/txn_summary.sql, filled by aml.memo.features
-- from typed values (quoted CIFs, DATE literals); the window is [window_start, window_end_next).
SELECT DISTINCT l.txn_id AS txn_id,
       t.memo            AS memo
FROM txn_legs l
JOIN transactions t ON t.txn_id = l.txn_id
WHERE {cif_filter}
  AND l.txn_ts >= {window_start}
  AND l.txn_ts < {window_end_next};
