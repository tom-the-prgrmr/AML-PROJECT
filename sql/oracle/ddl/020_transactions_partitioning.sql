-- Phase 2a: transactions -> monthly interval partitioning (spec oracle-schema-core).
-- Idempotent: NOT NULL is swallowed if already set; the conversion runs only while the
-- table is still a heap. PK (txn_id) stays a global index; txn_ts local indexes follow.

BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE transactions MODIFY (txn_ts NOT NULL)';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -1442 THEN RAISE; END IF;   -- ORA-01442: column already NOT NULL
END;
/

DECLARE
  v_parted NUMBER;
  v_idx    VARCHAR2(200);
BEGIN
  SELECT COUNT(*) INTO v_parted FROM user_part_tables WHERE table_name = 'TRANSACTIONS';
  IF v_parted = 0 THEN
    -- Already-existing heap txn_ts indexes must be listed so they become LOCAL.
    FOR r IN (SELECT index_name FROM user_indexes
              WHERE table_name = 'TRANSACTIONS'
                AND index_name IN ('IX_TXN_FROM_TS', 'IX_TXN_TO_TS')
              ORDER BY index_name) LOOP
      v_idx := v_idx || CASE WHEN v_idx IS NULL THEN '' ELSE ', ' END || r.index_name || ' LOCAL';
    END LOOP;
    EXECUTE IMMEDIATE
      'ALTER TABLE transactions MODIFY PARTITION BY RANGE (txn_ts) '
      || 'INTERVAL (NUMTOYMINTERVAL(1,''MONTH'')) '
      || '(PARTITION p_before_2000 VALUES LESS THAN (TIMESTAMP ''2000-01-01 00:00:00'')) '
      || 'ONLINE UPDATE INDEXES'
      || CASE WHEN v_idx IS NULL THEN '' ELSE ' (' || v_idx || ')' END;
  END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE
    'CREATE INDEX ix_txn_from_ts ON transactions (from_account_id, txn_ts) LOCAL';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE NOT IN (-955, -1408) THEN RAISE; END IF;   -- name used / column list indexed
END;
/

BEGIN
  EXECUTE IMMEDIATE
    'CREATE INDEX ix_txn_to_ts ON transactions (to_account_id, txn_ts) LOCAL';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE NOT IN (-955, -1408) THEN RAISE; END IF;
END;
/
