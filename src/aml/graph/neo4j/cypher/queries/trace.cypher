// Fund-flow trace (method neo4j): money out of $account, up to $hops hops within $hours hours of the
// first hop, hops in strict time order, no account revisited. One MATCH per hop; every prefix is a row.
MATCH (a0:Account {account_id: $account})-[e1:TRANSFERRED_TO]->(a1:Account)
WHERE $since IS NULL OR e1.ts >= $since
WITH e1.ts AS t0, e1.ts + duration({hours: $hours}) AS t1, [a0, a1] AS ns, [e1] AS es, a1 = a0 AS cyc
CALL (t1, ns, es, cyc) {
  RETURN ns AS ns2, es AS es2, cyc AS cyc2
  UNION ALL
  WITH t1, ns, es, cyc WHERE NOT cyc AND size(es) = 1 AND $hops >= 2
  WITH t1, ns, es, ns[-1] AS last, es[-1].ts AS ts
  MATCH (last)-[e:TRANSFERRED_TO]->(nx:Account)
  WHERE e.ts > ts AND e.ts <= t1
  RETURN ns + nx AS ns2, es + e AS es2, nx IN ns AS cyc2
}
WITH t0, t1, ns2 AS ns, es2 AS es, cyc2 AS cyc
CALL (t1, ns, es, cyc) {
  RETURN ns AS ns3, es AS es3, cyc AS cyc3
  UNION ALL
  WITH t1, ns, es, cyc WHERE NOT cyc AND size(es) = 2 AND $hops >= 3
  WITH t1, ns, es, ns[-1] AS last, es[-1].ts AS ts
  MATCH (last)-[e:TRANSFERRED_TO]->(nx:Account)
  WHERE e.ts > ts AND e.ts <= t1
  RETURN ns + nx AS ns3, es + e AS es3, nx IN ns AS cyc3
}
WITH t0, t1, ns3 AS ns, es3 AS es, cyc3 AS cyc
CALL (t1, ns, es, cyc) {
  RETURN ns AS ns4, es AS es4, cyc AS cyc4
  UNION ALL
  WITH t1, ns, es, cyc WHERE NOT cyc AND size(es) = 3 AND $hops >= 4
  WITH t1, ns, es, ns[-1] AS last, es[-1].ts AS ts
  MATCH (last)-[e:TRANSFERRED_TO]->(nx:Account)
  WHERE e.ts > ts AND e.ts <= t1
  RETURN ns + nx AS ns4, es + e AS es4, nx IN ns AS cyc4
}
WITH t0, t1, ns4 AS ns, es4 AS es, cyc4 AS cyc
CALL (t1, ns, es, cyc) {
  RETURN ns AS ns5, es AS es5, cyc AS cyc5
  UNION ALL
  WITH t1, ns, es, cyc WHERE NOT cyc AND size(es) = 4 AND $hops >= 5
  WITH t1, ns, es, ns[-1] AS last, es[-1].ts AS ts
  MATCH (last)-[e:TRANSFERRED_TO]->(nx:Account)
  WHERE e.ts > ts AND e.ts <= t1
  RETURN ns + nx AS ns5, es + e AS es5, nx IN ns AS cyc5
}
WITH t0, t1, ns5 AS ns, es5 AS es, cyc5 AS cyc
CALL (t1, ns, es, cyc) {
  RETURN ns AS ns6, es AS es6, cyc AS cyc6
  UNION ALL
  WITH t1, ns, es, cyc WHERE NOT cyc AND size(es) = 5 AND $hops >= 6
  WITH t1, ns, es, ns[-1] AS last, es[-1].ts AS ts
  MATCH (last)-[e:TRANSFERRED_TO]->(nx:Account)
  WHERE e.ts > ts AND e.ts <= t1
  RETURN ns + nx AS ns6, es + e AS es6, nx IN ns AS cyc6
}
WITH t0, t1, ns6 AS ns, es6 AS es, cyc6 AS cyc
RETURN size(es) AS hop, reduce(s = ns[0].account_id, n IN ns[1..] | s + '>' + n.account_id) AS path,
       ns[-1].account_id AS account_id,
       reduce(s = es[0].txn_id, x IN es[1..] | s + '>' + x.txn_id) AS step_path,
       t0 AS first_ts, es[-1].ts AS last_ts, es[-1].amount AS amount_vnd, cyc AS is_cycle
LIMIT $row_limit;
