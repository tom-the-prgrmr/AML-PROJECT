// Transfers in [$start, $end) that touch an account of the customer: in (received from someone
// else), out (sent to someone else), own (both ends belong to the customer). Always one row.
MATCH (c:Customer {golden_customer_id: $customer})
OPTIONAL MATCH (c)-[:OWNS]->(a:Account)
WITH collect(a) AS mine
UNWIND mine AS a
MATCH (a)-[r:TRANSFERRED_TO]-(:Account)
WHERE r.ts >= $start AND r.ts < $end
WITH DISTINCT r, mine
WITH r, startNode(r) IN mine AS from_mine, endNode(r) IN mine AS to_mine
RETURN count(r) AS transfers,
       sum(CASE WHEN to_mine AND NOT from_mine THEN 1 ELSE 0 END) AS in_count,
       sum(CASE WHEN to_mine AND NOT from_mine THEN r.amount ELSE 0 END) AS in_vnd,
       sum(CASE WHEN from_mine AND NOT to_mine THEN 1 ELSE 0 END) AS out_count,
       sum(CASE WHEN from_mine AND NOT to_mine THEN r.amount ELSE 0 END) AS out_vnd,
       sum(CASE WHEN from_mine AND to_mine THEN 1 ELSE 0 END) AS own_count;
