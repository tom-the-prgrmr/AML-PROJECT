UNWIND $rows AS row
MATCH (a:Account {account_id: row.src})
MATCH (b:Account {account_id: row.dst})
MERGE (a)-[r:SENT_TO {day: row.day}]->(b)
SET r.count = row.count, r.total = row.total;
