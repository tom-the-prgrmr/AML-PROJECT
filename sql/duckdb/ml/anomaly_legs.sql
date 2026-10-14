-- Phase 7b-i: every account side (leg) of a transaction before the cutoff, with the owner CIF.
-- {cutoff} is replaced by a TIMESTAMP literal; the window of each month is cut in Python.
SELECT l.cif, l.account_id, l.txn_id, l.txn_ts, l.direction, l.amount_vnd, l.counterparty_id,
       l.channel
FROM txn_legs l
WHERE l.txn_ts < {cutoff};
