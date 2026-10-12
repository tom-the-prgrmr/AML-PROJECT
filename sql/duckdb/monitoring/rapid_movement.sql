-- RAPID_MOVEMENT: a large inflow that is passed on within the window.
WITH q AS (
    SELECT account_id, txn_id, txn_ts, direction, amount_vnd
    FROM txn_legs
    WHERE txn_ts < {cutoff}
),
hits AS (
    SELECT a.account_id, a.txn_ts AS anchor_ts
    FROM q a
    JOIN q b ON b.account_id = a.account_id AND b.txn_ts >= a.txn_ts AND b.txn_ts < a.txn_ts + INTERVAL {window_hours} HOUR
    WHERE a.direction = 'IN'
    GROUP BY a.account_id, a.txn_id, a.txn_ts
    HAVING SUM(CASE WHEN b.direction = 'IN' THEN b.amount_vnd ELSE 0 END) >= {min_inflow_vnd}
       AND SUM(CASE WHEN b.direction = 'OUT' AND b.txn_ts > a.txn_ts THEN b.amount_vnd ELSE 0 END)
           >= {min_pass_through_pct} * SUM(CASE WHEN b.direction = 'IN' THEN b.amount_vnd ELSE 0 END)
),
marked AS (
    SELECT account_id, anchor_ts,
           CASE WHEN anchor_ts <= LAG(anchor_ts) OVER (PARTITION BY account_id ORDER BY anchor_ts) + INTERVAL {window_hours} HOUR
                THEN 0 ELSE 1 END AS is_start
    FROM (SELECT DISTINCT account_id, anchor_ts FROM hits) h
),
grouped AS (
    SELECT account_id, anchor_ts,
           SUM(is_start) OVER (PARTITION BY account_id ORDER BY anchor_ts) AS episode_no
    FROM marked
),
episodes AS (
    SELECT account_id, episode_no, MIN(anchor_ts) AS window_start, MAX(anchor_ts) + INTERVAL {window_hours} HOUR AS scan_end
    FROM grouped
    GROUP BY account_id, episode_no
)
SELECT e.account_id, e.window_start,
       MAX(q.txn_ts) OVER (PARTITION BY e.account_id, e.episode_no) AS window_end,
       q.txn_id, q.amount_vnd,
       SUM(CASE WHEN q.direction = 'IN' THEN q.amount_vnd ELSE 0 END)
           OVER (PARTITION BY e.account_id, e.episode_no) AS in_vnd,
       SUM(CASE WHEN q.direction = 'OUT' THEN q.amount_vnd ELSE 0 END)
           OVER (PARTITION BY e.account_id, e.episode_no) AS out_vnd
FROM episodes e
JOIN q ON q.account_id = e.account_id AND q.txn_ts >= e.window_start AND q.txn_ts < e.scan_end;
