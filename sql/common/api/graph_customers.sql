-- Phase 9b: names of the customers shown in the case graph.
-- {customers_table} is customers or customers_masked (by role), {cif_filter} a condition on cif.
SELECT cif,
       full_name
FROM {customers_table}
WHERE {cif_filter}
