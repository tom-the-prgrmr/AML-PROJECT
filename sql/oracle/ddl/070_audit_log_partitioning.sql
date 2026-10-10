-- Phase 2c-i: audit_log -> monthly interval partitioning on event_ts (spec oracle-retention).
-- Idempotent: the conversion runs only while the table is still a heap. The identity PK stays
-- a global index. ONLINE keeps the append-only triggers (verified on a scratch clone); the
-- triggers are recompiled by ddl/050_security_objects.sql, which runs after this script.

DECLARE
  v_parted NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_parted FROM user_part_tables WHERE table_name = 'AUDIT_LOG';
  IF v_parted = 0 THEN
    EXECUTE IMMEDIATE
      'ALTER TABLE audit_log MODIFY PARTITION BY RANGE (event_ts) '
      || 'INTERVAL (NUMTOYMINTERVAL(1,''MONTH'')) '
      || '(PARTITION p_before_2000 VALUES LESS THAN (TIMESTAMP ''2000-01-01 00:00:00'')) '
      || 'ONLINE UPDATE INDEXES';
  END IF;
END;
/
