UNWIND $rows AS row
MATCH (c:Customer {golden_customer_id: row.golden_customer_id})
MATCH (a:Account {account_id: row.account_id})
MERGE (c)-[o:OWNS]->(a)
SET o.cif = row.cif, o.synced_run = $run_id;
