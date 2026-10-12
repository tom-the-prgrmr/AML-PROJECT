-- DORMANT_REACTIVATION: no activity for a long time, then a large amount within the window.
WITH q AS (
    SELECT account_id, open_date, txn_id, txn_ts, amount_vnd
    FROM txn_legs
    WHERE txn_ts < {cutoff}
),
gaps AS (
    SELECT q.account_id, q.txn_ts,
           GREATEST(
               COALESCE(LAG(q.txn_ts) OVER (PARTITION BY q.account_id ORDER BY q.txn_ts, q.txn_id),
                        (SELECT MIN(txn_ts) FROM transactions)),
               CAST(q.open_date AS TIMESTAMP)) AS quiet_since
    FROM q
),
wake AS (
    SELECT DISTINCT account_id, txn_ts AS window_start, txn_ts + NUMTODSINTERVAL({window_hours}, 'HOUR') AS scan_end, quiet_since
    FROM gaps
    WHERE txn_ts >= quiet_since + NUMTODSINTERVAL({dormant_days}, 'DAY')
),
ev AS (
    SELECT w.account_id, w.window_start,
           MAX(q.txn_ts) OVER (PARTITION BY w.account_id, w.window_start) AS window_end,
           q.txn_id, q.amount_vnd,
           EXTRACT(DAY FROM (w.window_start - w.quiet_since)) AS quiet_days,
           COUNT(*) OVER (PARTITION BY w.account_id, w.window_start) AS txns,
           SUM(q.amount_vnd) OVER (PARTITION BY w.account_id, w.window_start) AS total_vnd
    FROM wake w
    JOIN q ON q.account_id = w.account_id AND q.txn_ts >= w.window_start AND q.txn_ts < w.scan_end
)
SELECT account_id, window_start, window_end, txn_id, amount_vnd, quiet_days, txns, total_vnd
FROM ev
WHERE total_vnd >= {min_amount_vnd}
/
