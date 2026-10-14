// Other customers that carry the same device, phone or address value as the customer. A value
// held by more than $max_customers_per_value customers is skipped (a public device, a call
// centre number). One row per (other customer, kind); the hashed key itself is never returned.
MATCH (c:Customer {golden_customer_id: $customer})-[:USES_DEVICE|HAS_PHONE|LIVES_AT]->(v)
MATCH (o:Customer)-[:USES_DEVICE|HAS_PHONE|LIVES_AT]->(v)
WITH v, collect(DISTINCT o.golden_customer_id) AS holders
WHERE size(holders) <= $max_customers_per_value
UNWIND holders AS other
WITH other, toLower(labels(v)[0]) AS kind
WHERE other <> $customer
RETURN DISTINCT other, kind
ORDER BY other, kind
LIMIT $limit;
