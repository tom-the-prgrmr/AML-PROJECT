-- Fund-flow trace on acct_edge_daily (DuckDB), approximate by day.
-- Binds: $account, $hops, $days, $since, $min_amount, $top_k, $row_limit.
-- A later edge has day >= the previous day (order inside a day is unknown); the last edge ends
-- within $days of the first. Per parent row only the $top_k biggest daily edges are followed
-- (ranked by total_amount desc, dst_acct, day); $top_k = 0 means no limit. Rows that return to
-- an account already on the path are kept (is_cycle) but not extended.
WITH RECURSIVE walk AS (
    SELECT 0 AS hop,
           CAST($account AS VARCHAR) AS account_id,
           [CAST($account AS VARCHAR)] AS visited,
           CAST([] AS VARCHAR[]) AS steps,
           CAST(NULL AS DATE) AS first_day,
           CAST(NULL AS DATE) AS last_day,
           CAST(NULL AS BIGINT) AS amount_vnd,
           FALSE AS is_cycle,
           1 AS rk
    UNION ALL
    SELECT w.hop + 1,
           e.dst_acct,
           list_append(w.visited, e.dst_acct),
           list_append(w.steps, CAST(e.day AS VARCHAR)),
           COALESCE(w.first_day, e.day),
           e.day,
           CAST(e.total_amount AS BIGINT),
           list_contains(w.visited, e.dst_acct),
           ROW_NUMBER() OVER (
               PARTITION BY w.visited, w.steps
               ORDER BY e.total_amount DESC, e.dst_acct, e.day)
    FROM walk w
    JOIN acct_edge_daily e ON e.src_acct = w.account_id
    WHERE NOT w.is_cycle
      AND w.hop < $hops
      AND ($top_k = 0 OR w.rk <= $top_k)
      AND e.total_amount >= $min_amount
      AND (   (w.hop = 0 AND ($since IS NULL OR e.day >= CAST(CAST($since AS TIMESTAMP) AS DATE)))
           OR (w.hop > 0 AND e.day >= w.last_day AND e.day <= w.first_day + CAST($days AS INTEGER)))
)
SELECT hop,
       array_to_string(visited, '>') AS path,
       account_id,
       array_to_string(steps, '>') AS step_path,
       CAST(first_day AS TIMESTAMP) AS first_ts,
       CAST(last_day AS TIMESTAMP) AS last_ts,
       amount_vnd,
       is_cycle
FROM walk
WHERE hop > 0 AND ($top_k = 0 OR rk <= $top_k)
ORDER BY hop, path, step_path
LIMIT $row_limit
