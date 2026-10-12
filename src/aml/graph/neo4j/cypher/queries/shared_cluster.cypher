// Everyone reachable from $customer through shared devices, phones or addresses (shortest chain each).
MATCH (seed:Customer {golden_customer_id: $customer})
MATCH p = ANY SHORTEST (seed) ((:Customer)-[:USES_DEVICE|HAS_PHONE|LIVES_AT]->
              (v WHERE COUNT { (v)<--(:Customer) } <= $max_customers_per_value)
              <-[:USES_DEVICE|HAS_PHONE|LIVES_AT]-(:Customer)){1,} (member:Customer)
WHERE member <> seed
RETURN member.golden_customer_id AS customer, length(p) / 2 AS distance,
       [n IN nodes(p) WHERE NOT n:Customer | toLower(labels(n)[0])] AS via,
       COUNT { (member)-[:OWNS]->(:Account) } AS accounts
ORDER BY distance, customer
LIMIT $row_limit;
