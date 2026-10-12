UNWIND $rows AS row
MATCH (a:Account {account_id: row.src})
MATCH (b:Account {account_id: row.dst})
MERGE (a)-[r:TRANSFERRED_TO {txn_id: row.txn_id}]->(b)
SET r.amount = row.amount, r.ts = row.ts, r.channel = row.channel;
