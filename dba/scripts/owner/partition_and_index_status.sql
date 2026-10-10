-- Runs as aml_owner (read-only). Status: verified.
-- Partitions of transactions with row estimates, then index validity (UNUSABLE indexes break DML).
SELECT partition_name, partition_position, high_value_length, num_rows
FROM user_tab_partitions
WHERE table_name = 'TRANSACTIONS'
ORDER BY partition_position
/
SELECT index_name, table_name, status, partitioned
FROM user_indexes
ORDER BY table_name, index_name
/
SELECT index_name, partition_name, status
FROM user_ind_partitions
WHERE status <> 'USABLE'
ORDER BY index_name, partition_name
/
