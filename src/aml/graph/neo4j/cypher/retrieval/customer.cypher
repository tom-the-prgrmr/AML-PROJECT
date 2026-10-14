// One golden customer and the accounts it owns (one row per account; one row with nulls when it
// owns none). No row means the customer is not in the graph.
MATCH (c:Customer {golden_customer_id: $customer})
OPTIONAL MATCH (c)-[o:OWNS]->(a:Account)
RETURN c.golden_customer_id AS golden_customer_id, c.cif_count AS cif_count,
       a.account_id AS account_id, o.cif AS cif, a.account_type AS account_type,
       a.currency AS currency, a.open_date AS open_date
ORDER BY account_id;
