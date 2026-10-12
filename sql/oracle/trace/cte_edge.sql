-- Fund-flow trace on acct_edge_daily (Oracle), approximate by day.
-- Binds: :account, :hops, :days, :since, :min_amount, :top_k, :row_limit.
-- A later edge has day >= the previous day (order inside a day is unknown); the last edge ends
-- within :days of the first. Per parent row only the :top_k biggest daily edges are followed
-- (ranked by total_amount desc, dst_acct, day); :top_k = 0 means no limit. CYCLE keeps a row that
-- returns to an account already on the path (is_cycle = 'Y') and does not extend it.
WITH walk (hop, account_id, path, step_path, first_day, last_day, amount_vnd, rk) AS (
    SELECT 0,
           CAST(:account AS VARCHAR2(40 CHAR)),
           CAST(:account AS VARCHAR2(200 CHAR)),
           CAST(NULL AS VARCHAR2(200 CHAR)),
           CAST(NULL AS DATE),
           CAST(NULL AS DATE),
           CAST(NULL AS NUMBER),
           1
    FROM dual
    UNION ALL
    SELECT w.hop + 1,
           e.dst_acct,
           w.path || '>' || e.dst_acct,
           CASE WHEN w.hop = 0 THEN TO_CHAR(e.day, 'YYYY-MM-DD')
                ELSE w.step_path || '>' || TO_CHAR(e.day, 'YYYY-MM-DD') END,
           COALESCE(w.first_day, e.day),
           e.day,
           e.total_amount,
           ROW_NUMBER() OVER (
               PARTITION BY w.path, w.step_path
               ORDER BY e.total_amount DESC, e.dst_acct, e.day)
    FROM walk w
    JOIN acct_edge_daily e ON e.src_acct = w.account_id
    WHERE w.hop < :hops
      AND (:top_k = 0 OR w.rk <= :top_k)
      AND e.total_amount >= :min_amount
      AND (   (w.hop = 0 AND (:since IS NULL OR e.day >= TRUNC(CAST(:since AS TIMESTAMP))))
           OR (w.hop > 0 AND e.day >= w.last_day AND e.day <= w.first_day + :days))
)
CYCLE account_id SET is_cycle TO 'Y' DEFAULT 'N'
SELECT hop, path, account_id, step_path,
       CAST(first_day AS TIMESTAMP) AS first_ts,
       CAST(last_day AS TIMESTAMP) AS last_ts,
       amount_vnd, is_cycle
FROM walk
WHERE hop > 0 AND (:top_k = 0 OR rk <= :top_k)
FETCH FIRST :row_limit ROWS ONLY
/
