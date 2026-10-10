-- REFERENCE ONLY: never run here (retention purge in src/aml/dba/retention.py owns real drops).
-- Dropping a partition invalidates GLOBAL indexes (ORA-01502 on later DML) unless they are
-- maintained in the same statement. LOCAL indexes follow the partition automatically.
ALTER TABLE transactions DROP PARTITION p_2026_01 UPDATE GLOBAL INDEXES
/
-- The sentinel partition p_before_2000 cannot be dropped when it is the only partition left:
-- ORA-14758 (last partition in the range section cannot be dropped).
-- Check afterwards: SELECT index_name, status FROM user_indexes WHERE status <> 'VALID'
