-- HIGH_VELOCITY: a burst of transactions, ignoring long-known counterparties.
WITH q AS (
    SELECT l.account_id, l.txn_id, l.txn_ts, l.amount_vnd
    FROM txn_legs l
    WHERE l.txn_ts < {cutoff}
      AND NOT EXISTS (
            SELECT 1 FROM txn_legs k
            WHERE k.account_id = l.account_id AND k.counterparty_id = l.counterparty_id
              AND k.txn_ts <= l.txn_ts - NUMTODSINTERVAL({known_counterparty_days}, 'DAY'))
),
hits AS (
    SELECT a.account_id, a.txn_ts AS anchor_ts
    FROM q a
    JOIN q b ON b.account_id = a.account_id AND b.txn_ts >= a.txn_ts AND b.txn_ts < a.txn_ts + NUMTODSINTERVAL({window_hours}, 'HOUR')
    WHERE a.txn_ts >= (SELECT MIN(txn_ts) FROM transactions) + NUMTODSINTERVAL({known_counterparty_days}, 'DAY')
    GROUP BY a.account_id, a.txn_id, a.txn_ts
    HAVING COUNT(*) >= {min_txns} AND SUM(b.amount_vnd) >= {min_total_vnd}
),
marked AS (
    SELECT account_id, anchor_ts,
           CASE WHEN anchor_ts <= LAG(anchor_ts) OVER (PARTITION BY account_id ORDER BY anchor_ts) + NUMTODSINTERVAL({window_hours}, 'HOUR')
                THEN 0 ELSE 1 END AS is_start
    FROM (SELECT DISTINCT account_id, anchor_ts FROM hits) h
),
grouped AS (
    SELECT account_id, anchor_ts,
           SUM(is_start) OVER (PARTITION BY account_id ORDER BY anchor_ts) AS episode_no
    FROM marked
),
episodes AS (
    SELECT account_id, episode_no, MIN(anchor_ts) AS window_start, MAX(anchor_ts) + NUMTODSINTERVAL({window_hours}, 'HOUR') AS scan_end
    FROM grouped
    GROUP BY account_id, episode_no
)
SELECT e.account_id, e.window_start,
       MAX(q.txn_ts) OVER (PARTITION BY e.account_id, e.episode_no) AS window_end,
       q.txn_id, q.amount_vnd,
       COUNT(*) OVER (PARTITION BY e.account_id, e.episode_no) AS txns,
       SUM(q.amount_vnd) OVER (PARTITION BY e.account_id, e.episode_no) AS total_vnd
FROM episodes e
JOIN q ON q.account_id = e.account_id AND q.txn_ts >= e.window_start AND q.txn_ts < e.scan_end
/
