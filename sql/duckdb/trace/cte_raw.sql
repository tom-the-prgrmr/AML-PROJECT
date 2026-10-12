-- Fund-flow trace on raw transactions (DuckDB). Binds: $account, $hops, $hours, $since, $row_limit.
-- Hop 0 is the start account itself. A hop must be strictly later than the previous one and end
-- within $hours of the FIRST hop of its path. A row that returns to an account already on the
-- path is kept (is_cycle) but never extended: `visited` is carried as a list.
WITH RECURSIVE walk AS (
    SELECT 0 AS hop,
           CAST($account AS VARCHAR) AS account_id,
           [CAST($account AS VARCHAR)] AS visited,
           CAST([] AS VARCHAR[]) AS steps,
           CAST(NULL AS TIMESTAMP) AS first_ts,
           CAST(NULL AS TIMESTAMP) AS last_ts,
           CAST(NULL AS BIGINT) AS amount_vnd,
           FALSE AS is_cycle
    UNION ALL
    SELECT w.hop + 1,
           t.to_account_id,
           list_append(w.visited, t.to_account_id),
           list_append(w.steps, t.txn_id),
           COALESCE(w.first_ts, t.txn_ts),
           t.txn_ts,
           CAST(t.amount_vnd AS BIGINT),
           list_contains(w.visited, t.to_account_id)
    FROM walk w
    JOIN transactions t ON t.from_account_id = w.account_id
    WHERE NOT w.is_cycle
      AND w.hop < $hops
      AND t.to_account_id IS NOT NULL
      AND (   (w.hop = 0 AND ($since IS NULL OR t.txn_ts >= CAST($since AS TIMESTAMP)))
           OR (w.hop > 0 AND t.txn_ts > w.last_ts AND t.txn_ts <= w.first_ts + to_hours($hours)))
)
SELECT hop,
       array_to_string(visited, '>') AS path,
       account_id,
       array_to_string(steps, '>') AS step_path,
       first_ts,
       last_ts,
       amount_vnd,
       is_cycle
FROM walk
WHERE hop > 0
ORDER BY hop, path, step_path
LIMIT $row_limit
