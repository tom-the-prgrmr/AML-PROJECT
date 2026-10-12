-- Fund-flow trace on raw transactions (Oracle). Binds: :account, :hops, :hours, :since, :row_limit.
-- Hop 0 is the start account itself. A hop must be strictly later than the previous one and end
-- within :hours of the FIRST hop of its path. CYCLE keeps a row that returns to an account already
-- on the path (is_cycle = 'Y') and does not extend it.
WITH walk (hop, account_id, path, step_path, first_ts, last_ts, amount_vnd) AS (
    SELECT 0,
           CAST(:account AS VARCHAR2(40 CHAR)),
           CAST(:account AS VARCHAR2(200 CHAR)),
           CAST(NULL AS VARCHAR2(200 CHAR)),
           CAST(NULL AS TIMESTAMP(0)),
           CAST(NULL AS TIMESTAMP(0)),
           CAST(NULL AS NUMBER(18))
    FROM dual
    UNION ALL
    SELECT w.hop + 1,
           t.to_account_id,
           w.path || '>' || t.to_account_id,
           CASE WHEN w.hop = 0 THEN t.txn_id ELSE w.step_path || '>' || t.txn_id END,
           COALESCE(w.first_ts, t.txn_ts),
           t.txn_ts,
           t.amount_vnd
    FROM walk w
    JOIN transactions t ON t.from_account_id = w.account_id
    WHERE w.hop < :hops
      AND t.to_account_id IS NOT NULL
      AND (   (w.hop = 0 AND (:since IS NULL OR t.txn_ts >= CAST(:since AS TIMESTAMP)))
           OR (w.hop > 0 AND t.txn_ts > w.last_ts
               AND t.txn_ts <= w.first_ts + NUMTODSINTERVAL(:hours, 'HOUR')))
)
CYCLE account_id SET is_cycle TO 'Y' DEFAULT 'N'
SELECT hop, path, account_id, step_path, first_ts, last_ts, amount_vnd, is_cycle
FROM walk
WHERE hop > 0
FETCH FIRST :row_limit ROWS ONLY
/
