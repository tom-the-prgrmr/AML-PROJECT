// Devices, phones and addresses carried by 2..$max_customers_per_value customers (keys are hashes).
MATCH (c:Customer)-[:USES_DEVICE|HAS_PHONE|LIVES_AT]->(v)
WITH v, c ORDER BY c.golden_customer_id
WITH v, collect(c.golden_customer_id) AS customer_ids
WHERE size(customer_ids) >= 2 AND size(customer_ids) <= $max_customers_per_value
  AND ($customer IS NULL OR $customer IN customer_ids)
RETURN toLower(labels(v)[0]) AS kind, v.key AS key, size(customer_ids) AS customers, customer_ids
ORDER BY customers DESC, kind, key
LIMIT $row_limit;
