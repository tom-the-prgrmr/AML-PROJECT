// At most $limit transfers of the customer in [$start, $end): the ones named in $evidence_ids
// first, then the largest amounts, then by txn_id. With $with_owners (hops >= 3) each end also
// carries the golden customer that owns it (null for an external account).
MATCH (c:Customer {golden_customer_id: $customer})-[:OWNS]->(a:Account)
MATCH (a)-[r:TRANSFERRED_TO]-(:Account)
WHERE r.ts >= $start AND r.ts < $end
WITH DISTINCT r
WITH r, startNode(r) AS s, endNode(r) AS d,
     CASE WHEN r.txn_id IN $evidence_ids THEN 0 ELSE 1 END AS rank
ORDER BY rank, r.amount DESC, r.txn_id
LIMIT $limit
OPTIONAL MATCH (so:Customer)-[:OWNS]->(s) WHERE $with_owners
OPTIONAL MATCH (dn:Customer)-[:OWNS]->(d) WHERE $with_owners
RETURN r.txn_id AS txn_id, s.account_id AS src, d.account_id AS dst, r.amount AS amount,
       r.ts AS ts, r.channel AS channel, so.golden_customer_id AS src_owner,
       dn.golden_customer_id AS dst_owner, rank
ORDER BY rank, amount DESC, txn_id;
