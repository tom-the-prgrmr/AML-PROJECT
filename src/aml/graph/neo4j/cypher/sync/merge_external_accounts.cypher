// Account codes that only appear as a transfer counterparty: minimal node, no OWNS.
UNWIND $rows AS row
MERGE (a:Account {account_id: row.account_id})
ON CREATE SET a.is_external = true;
