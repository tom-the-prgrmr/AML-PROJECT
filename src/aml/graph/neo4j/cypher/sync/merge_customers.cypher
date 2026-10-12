// Customer side of the projection: one node per golden customer, stamped with this run.
UNWIND $rows AS row
MERGE (c:Customer {golden_customer_id: row.golden_customer_id})
SET c.cifs = row.cifs, c.cif_count = row.cif_count, c.synced_run = $run_id;
