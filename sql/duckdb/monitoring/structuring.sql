-- STRUCTURING: repeated cash deposits just under the large-cash reporting threshold.
-- One row per (alert, evidence transaction).
WITH q AS (
    SELECT account_id, txn_id, txn_ts, amount_vnd, branch_id
    FROM txn_legs
    WHERE direction = 'IN' AND channel = 'CASH'
      AND amount_vnd >= {band_low_vnd} AND amount_vnd < {large_cash_vnd}
      AND txn_ts < {cutoff}
),
hits AS (
    SELECT a.account_id, a.txn_ts AS anchor_ts
    FROM q a
    JOIN q b ON b.account_id = a.account_id AND b.txn_ts >= a.txn_ts AND b.txn_ts < a.txn_ts + INTERVAL {window_days} DAY
    GROUP BY a.account_id, a.txn_id, a.txn_ts
    HAVING COUNT(*) >= {min_deposits}
),
marked AS (
    SELECT account_id, anchor_ts,
           CASE WHEN anchor_ts <= LAG(anchor_ts) OVER (PARTITION BY account_id ORDER BY anchor_ts) + INTERVAL {window_days} DAY
                THEN 0 ELSE 1 END AS is_start
    FROM (SELECT DISTINCT account_id, anchor_ts FROM hits) h
),
grouped AS (
    SELECT account_id, anchor_ts,
           SUM(is_start) OVER (PARTITION BY account_id ORDER BY anchor_ts) AS episode_no
    FROM marked
),
episodes AS (
    SELECT account_id, episode_no, MIN(anchor_ts) AS window_start, MAX(anchor_ts) + INTERVAL {window_days} DAY AS scan_end
    FROM grouped
    GROUP BY account_id, episode_no
)
SELECT e.account_id, e.window_start,
       MAX(q.txn_ts) OVER (PARTITION BY e.account_id, e.episode_no) AS window_end,
       q.txn_id, q.amount_vnd,
       COUNT(*) OVER (PARTITION BY e.account_id, e.episode_no) AS deposits,
       SUM(q.amount_vnd) OVER (PARTITION BY e.account_id, e.episode_no) AS total_vnd,
       COUNT(DISTINCT q.branch_id) OVER (PARTITION BY e.account_id, e.episode_no) AS branches
FROM episodes e
JOIN q ON q.account_id = e.account_id AND q.txn_ts >= e.window_start AND q.txn_ts < e.scan_end;
