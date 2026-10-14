-- Phase 8e golden set: the transactions named by those ground-truth rows. The memo is read only to
-- find which injection phrase it ends with; it is never written to the golden set.
SELECT t.txn_id, t.txn_ts, t.from_account_id, t.to_account_id, t.amount_vnd, t.memo
FROM transactions t
WHERE t.txn_id IN (
    SELECT entity_id
    FROM ground_truth
    WHERE entity_type = 'transaction'
      AND typology IN ('structuring', 'rapid_movement', 'round_tripping', 'mule_ring', 'prompt_injection')
);
