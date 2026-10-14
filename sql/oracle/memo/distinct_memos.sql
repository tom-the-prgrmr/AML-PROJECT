-- Phase 8d: every distinct raw memo with the number of transactions that carry it (the NULL group
-- is the transactions without a memo). aml.memo.runner normalises the memos in Python and groups
-- them by key, so both backends give the same keys.
SELECT t.memo   AS memo,
       COUNT(*) AS transactions
FROM transactions t
GROUP BY t.memo
/
