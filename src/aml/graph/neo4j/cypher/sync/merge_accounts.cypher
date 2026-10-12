// Accounts that exist in the `accounts` table (is_external = false).
UNWIND $rows AS row
MERGE (a:Account {account_id: row.account_id})
SET a.cif = row.cif, a.account_type = row.account_type, a.branch_id = row.branch_id,
    a.open_date = row.open_date, a.currency = row.currency, a.is_external = false;
