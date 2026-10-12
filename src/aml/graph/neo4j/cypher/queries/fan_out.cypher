// Fan-out: accounts with at least $min_counterparties distinct receivers inside $window_days days.
MATCH (a:Account {is_external: false})-[e:TRANSFERRED_TO]->(:Account)
WHERE e.ts < $cutoff AND ($account IS NULL OR a.account_id = $account)
CALL (a, e) {
  MATCH (a)-[w:TRANSFERRED_TO]->(other:Account)
  WHERE w.ts >= e.ts AND w.ts < e.ts + duration({days: $window_days}) AND w.ts < $cutoff
  RETURN count(DISTINCT other) AS counterparties, count(w) AS transfers, sum(w.amount) AS total_vnd,
         max(w.ts) AS last_ts
}
WITH a, e, counterparties, transfers, total_vnd, last_ts
WHERE counterparties >= $min_counterparties AND total_vnd >= $min_total_vnd
WITH a, e, counterparties, transfers, total_vnd, last_ts
ORDER BY a.account_id, counterparties DESC, total_vnd DESC, e.ts, e.txn_id
WITH a, collect({ts: e.ts, last_ts: last_ts, counterparties: counterparties, transfers: transfers,
                 total_vnd: total_vnd}) AS windows
RETURN a.account_id AS account_id, windows[0].ts AS window_start, windows[0].last_ts AS window_end,
       windows[0].counterparties AS counterparties, windows[0].transfers AS transfers,
       windows[0].total_vnd AS total_vnd
ORDER BY counterparties DESC, account_id
LIMIT $row_limit;
