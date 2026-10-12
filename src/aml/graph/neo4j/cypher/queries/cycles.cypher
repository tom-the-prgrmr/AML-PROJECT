// Round-tripping: time-ordered cycles of $min_length..$max_length transfers between accounts of different customers.
MATCH (a:Account {is_external: false})-[e1:TRANSFERRED_TO]->(b:Account {is_external: false})
WHERE e1.amount >= $min_amount AND e1.ts < $cutoff
MATCH p = (b) ((:Account {is_external: false})-[r:TRANSFERRED_TO]->(:Account {is_external: false})
               WHERE r.amount >= $min_amount AND r.ts > e1.ts AND r.ts < $cutoff
                 AND r.ts < e1.ts + duration({hours: $window_hours})){2,5} (a)
WHERE size(r) + 1 >= $min_length AND size(r) + 1 <= $max_length
  AND all(i IN range(0, size(r) - 2) WHERE r[i].ts < r[i + 1].ts)
WITH [a] + nodes(p)[0..-1] AS members, [e1] + r AS hops
WHERE all(i IN range(1, size(members) - 1) WHERE NOT members[i] IN members[0..i])
WITH members, hops,
     [m IN members | head([(c:Customer)-[:OWNS]->(m) | c.golden_customer_id])] AS owners,
     reduce(lo = hops[0].amount, h IN hops | CASE WHEN h.amount < lo THEN h.amount ELSE lo END) AS lo,
     reduce(hi = hops[0].amount, h IN hops | CASE WHEN h.amount > hi THEN h.amount ELSE hi END) AS hi
WHERE all(i IN range(1, size(owners) - 1) WHERE NOT owners[i] IN owners[0..i])
  AND lo >= $min_amount_ratio * hi
  AND ($account IS NULL OR any(m IN members WHERE m.account_id = $account))
RETURN size(hops) AS length,
       reduce(s = members[0].account_id, m IN members[1..] | s + '>' + m.account_id) AS path,
       reduce(s = hops[0].txn_id, h IN hops[1..] | s + '>' + h.txn_id) AS step_path,
       hops[0].ts AS first_ts, hops[-1].ts AS last_ts,
       hops[0].amount AS first_vnd, hops[-1].amount AS last_vnd
ORDER BY first_ts, step_path
LIMIT $row_limit;
