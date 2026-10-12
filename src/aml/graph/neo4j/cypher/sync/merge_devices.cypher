// Shared-attribute node (hashed key) and the customer's link to it, both stamped with this run.
UNWIND $rows AS row
MATCH (c:Customer {golden_customer_id: row.golden_customer_id})
MERGE (x:Device {key: row.key})
SET x.synced_run = $run_id
MERGE (c)-[r:USES_DEVICE]->(x)
SET r.synced_run = $run_id;
